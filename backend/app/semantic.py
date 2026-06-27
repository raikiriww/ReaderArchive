from __future__ import annotations

import hashlib
import re
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

    @property
    def model_name(self) -> str:
        return self.settings.semantic_model_name

    @property
    def available(self) -> bool:
        return self._available

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def expected_dimensions(self) -> int:
        return self.settings.semantic_embedding_dimensions

    def preload(self) -> None:
        if not self._available:
            return
        self._load_model()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or not self._available:
            return []
        try:
            model = self._load_model()
            vectors = model.embed(texts)
            result = [[float(value) for value in vector] for vector in vectors]
            for vector in result:
                self.validate_dimensions(vector)
            self._last_error = None
            return result
        except Exception as exc:
            self._last_error = str(exc)
            self._available = False
            raise

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
            try:
                self._model = TextEmbedding(
                    model_name=self.settings.semantic_model_name,
                    cache_dir=str(self.settings.semantic_model_dir),
                    local_files_only=True,
                )
            except TypeError:
                self._model = TextEmbedding(
                    model_name=self.settings.semantic_model_name,
                    cache_dir=str(self.settings.semantic_model_dir),
                )
            return self._model
        except Exception as exc:
            self._last_error = str(exc)
            self._available = False
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
    try:
        html = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    extracted = _extract_with_trafilatura(html)
    if extracted:
        return extracted
    return _extract_with_html_parser(html)


def chunk_text(
    text: str,
    min_chars: int,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    paragraphs = [part for part in re.split(r"\n{2,}", text) if part.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        cleaned = normalize_text(paragraph)
        if not cleaned:
            continue
        if len(cleaned) <= max_chars:
            pieces.append(cleaned)
            continue
        pieces.extend(_split_long_text(cleaned, max_chars=max_chars))

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}".strip() if current else piece
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if len(current) >= min_chars:
            chunks.append(current)
            current = _overlap_suffix(current, overlap_chars)
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            current = candidate if len(candidate) <= max_chars else piece[:max_chars]
        else:
            chunks.append(candidate[:max_chars])
            current = candidate[max_chars - overlap_chars :]
    if len(current) >= min_chars:
        chunks.append(current)
    elif current and not chunks:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def normalize_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.splitlines()]
    text = "\n".join(line for line in lines if line)
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
    skip_tags = {"script", "style", "noscript", "svg", "canvas", "template"}
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
        if len(cleaned) >= 2:
            self.parts.append(cleaned)
