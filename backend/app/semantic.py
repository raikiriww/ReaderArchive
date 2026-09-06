from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass(frozen=True)
class PreparedSemanticDocument:
    text: str
    document_hash: str
    chunks: list[str]


class LocalEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._available = settings.semantic_search_enabled
        self._last_error: str | None = None
        self._failed_at = 0.0
        self._lock = threading.RLock()
        self._query_cache: dict[str, tuple[float, ...]] = {}

    @property
    def model_name(self) -> str:
        return self.settings.semantic_model_name

    @property
    def available(self) -> bool:
        return self.settings.semantic_search_enabled and (self._available or time.monotonic() - self._failed_at >= 60)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def expected_dimensions(self) -> int:
        return self.settings.semantic_embedding_dimensions

    def preload(self) -> None:
        if not self.available:
            return
        with self._lock:
            self._load_model()
            self._available = True
            self._last_error = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or not self.available:
            return []
        try:
            with self._lock:
                model = self._load_model()
                vectors = model.embed(texts)
                result = [[float(value) for value in vector] for vector in vectors]
            for vector in result:
                self.validate_dimensions(vector)
            self._last_error = None
            self._available = True
            return result
        except Exception as exc:
            self._last_error = str(exc)
            self._available = False
            self._failed_at = time.monotonic()
            raise

    def embed_query(self, query: str) -> tuple[float, ...]:
        cached = self._query_cache.get(query)
        if cached is not None:
            return cached
        if not self._lock.acquire(timeout=max(0, self.settings.semantic_query_lock_timeout_seconds)):
            raise RuntimeError("Semantic search is busy; keyword results remain available.")
        try:
            if self._model is None:
                raise RuntimeError("Semantic model is preparing; keyword results remain available.")
            if query in self._query_cache:
                return self._query_cache[query]
            embeddings = self.embed([query])
            if len(embeddings) != 1:
                raise RuntimeError("Query embedding was not generated.")
            if len(self._query_cache) >= 128:
                self._query_cache.pop(next(iter(self._query_cache)))
            result = tuple(embeddings[0])
            self._query_cache[query] = result
            return result
        finally:
            self._lock.release()

    def prepare_embedding_chunks(self, title: str, text: str) -> tuple[list[str], list[str]]:
        from tokenizers import Tokenizer

        with self._lock:
            model = self._load_model()
            original = model.model.tokenizer
            if original is None or not original.truncation:
                raise RuntimeError("The embedding tokenizer must declare its input limit.")
            budget = int(original.truncation["max_length"])
            tokenizer = Tokenizer.from_str(original.to_str())
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return token_budget_chunks(text, title, tokenizer, budget)

    def validate_dimensions(self, vector: list[float]) -> None:
        actual = len(vector)
        expected = self.expected_dimensions
        if actual != expected:
            msg = f"Embedding dimensions mismatch: expected {expected}, got {actual}."
            raise ValueError(msg)

    def _load_model(self):  # type: ignore[no-untyped-def]
        if self._model is not None:
            return self._model
        try:
            from fastembed import TextEmbedding

            self.settings.semantic_model_dir.mkdir(parents=True, exist_ok=True)
            self._model = TextEmbedding(
                model_name=self.settings.semantic_model_name,
                cache_dir=str(self.settings.semantic_model_dir),
                threads=self.settings.semantic_threads,
                providers=["CPUExecutionProvider"],
                local_files_only=True,
            )
            return self._model
        except Exception as exc:
            self._last_error = str(exc)
            self._available = False
            self._failed_at = time.monotonic()
            raise


class SemanticDocumentPreparer:
    def __init__(
        self,
        min_chars: int,
        max_chars: int,
        overlap_chars: int,
    ) -> None:
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def prepare(self, path: Path) -> PreparedSemanticDocument | None:
        text = extract_readable_text(path)
        if not text:
            return None
        chunks = chunk_text(
            text,
            min_chars=self.min_chars,
            max_chars=self.max_chars,
            overlap_chars=self.overlap_chars,
        )
        if not chunks:
            return None
        return PreparedSemanticDocument(
            text=text,
            document_hash=hash_text(text),
            chunks=chunks,
        )


def extract_readable_text(path: Path) -> str | None:
    if path.suffix.lower() == ".pdf":
        return _extract_from_pdf(path)
    try:
        html = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    extracted = _extract_with_trafilatura(html)
    if extracted:
        return extracted
    return _extract_with_html_parser(html)


def _extract_from_pdf(path: Path) -> str | None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    return None
            except Exception:
                return None
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return None
    return normalize_text(text) or None


def chunk_text(
    text: str,
    min_chars: int,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    # Work on contiguous ranges: no minimum-size rule may discard a document tail.
    # min_chars is a preference retained for configuration compatibility.
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    overlap = max(0, min(overlap_chars, max_chars - 1))
    value = normalize_text(text)
    chunks: list[str] = []
    start = 0
    while start < len(value):
        end = min(len(value), start + max_chars)
        if end < len(value):
            boundaries = list(re.finditer(r"\n\n|[。！？.!?](?:\s|(?=[^\x00-\x7f]))", value[start:end]))
            if boundaries and boundaries[-1].end() >= max(min_chars, max_chars // 2):
                end = start + boundaries[-1].end()
        chunk = value[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(value):
            break
        start = max(start + 1, end - overlap)
    return chunks


def normalize_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def semantic_texts_for_embedding(title: str, chunks: list[str]) -> list[str]:
    clean_title = normalize_text(title)
    if not clean_title:
        return chunks
    return [f"{clean_title}\n\n{chunk}" for chunk in chunks]


def _extract_with_trafilatura(html: str) -> str | None:
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_formatting=False,
            include_images=False,
            include_links=False,
            favor_recall=True,
            # Saved pages may keep application state/recommendations in
            # noscript or template elements. Those are not article prose.
            prune_xpath=['//script', '//style', '//noscript', '//template', '//svg', '//canvas'],
        )
    except Exception:
        return None
    cleaned = normalize_text(extracted or "")
    return cleaned or None


def _extract_with_html_parser(html: str) -> str | None:
    parser = _ReadableTextParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    cleaned = normalize_text("\n".join(parser.parts))
    return cleaned or None


def _split_long_text(text: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[。！？.!?])\s+", text)
    result: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                result.append(current)
                current = ""
            result.extend(sentence[index : index + max_chars] for index in range(0, len(sentence), max_chars))
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            result.append(current)
            current = sentence
    if current:
        result.append(current)
    return result


def _overlap_suffix(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    suffix = text[-overlap_chars:]
    split_at = suffix.find(" ")
    return suffix[split_at + 1 :].strip() if split_at > 0 else suffix.strip()


class _ReadableTextParser(HTMLParser):
    skip_tags = {"script", "style", "noscript", "svg", "canvas", "template", "nav", "footer"}
    block_tags = {
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "p",
        "pre",
        "section",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        name = tag.lower()
        if name in self.skip_tags:
            self._skip_depth += 1
        if name in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in self.skip_tags and self._skip_depth:
            self._skip_depth -= 1
        if name in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self.parts.append(cleaned)


def token_budget_chunks(text: str, title: str, tokenizer, budget: int) -> tuple[list[str], list[str]]:
    """Cover source characters while measuring the exact title + body model input."""
    def size(value: str) -> int:
        return len(tokenizer.encode(value).ids)

    clean_title = normalize_text(title)
    while clean_title and size(clean_title) > max(4, budget // 4):
        clean_title = clean_title[:max(0, len(clean_title) * 3 // 4)]
    prefix = f"{clean_title}\n\n" if clean_title else ""
    chunks: list[str] = []
    inputs: list[str] = []
    start = 0
    while start < len(text):
        low, high = start + 1, min(len(text), start + budget * 12)
        best = start
        while low <= high:
            end = (low + high) // 2
            if size(prefix + text[start:end]) <= budget:
                best = end
                low = end + 1
            else:
                high = end - 1
        if best == start:
            raise ValueError("Embedding input budget cannot fit one source character.")
        chunk = text[start:best]
        chunks.append(chunk)
        inputs.append(prefix + chunk)
        if best == len(text):
            break
        # Small overlap retains phrases at boundaries without hiding any tail.
        start = max(start + 1, best - min(16, (best - start) // 5))
    return chunks, inputs
