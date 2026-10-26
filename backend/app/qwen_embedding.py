"""Offline CPU Qwen embeddings with bounded, source-complete passage inputs.

The image ships the official Qwen tokenizer and Qdrant's ONNX export with
8-bit weights (fp32 activations), run by onnxruntime; torch is not needed.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.model_runtime import onnx_session, release_unused_memory, serialized_model_load

if TYPE_CHECKING:
    from app.core.config import Settings

MODEL_NAME = 'Qwen/Qwen3-Embedding-0.6B'
MODEL_REVISION = '97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3'
QUERY_INSTRUCTION = 'Given a web search query, retrieve relevant passages that answer the query'
MAX_INPUT_TOKENS = 512
ONNX_FILE = 'model.onnx'


class QwenTokenizer:
    """Wrap a ``tokenizers.Tokenizer`` with the calls chunking and batching use."""

    def __init__(self, tokenizer: Any) -> None:
        tokenizer.no_padding()
        tokenizer.no_truncation()
        pad_id = tokenizer.token_to_id('<|endoftext|>')
        if pad_id is None:
            raise ValueError('Qwen tokenizer has no <|endoftext|> padding token.')
        self._tokenizer = tokenizer
        self.pad_id = int(pad_id)

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        return list(self._tokenizer.encode(text, add_special_tokens=add_special_tokens).ids)

    def decode(self, ids: list[int]) -> str:
        return str(self._tokenizer.decode(ids, skip_special_tokens=False))

    def pad_batch(self, texts: list[str]) -> tuple[Any, Any]:
        """Left-pad, so the last position of every row is its final real token."""
        import numpy as np

        rows = [self.encode(text) for text in texts]
        width = max(map(len, rows))
        ids = np.full((len(rows), width), self.pad_id, dtype=np.int64)
        mask = np.zeros((len(rows), width), dtype=np.int64)
        for index, row in enumerate(rows):
            ids[index, width-len(row):] = row
            mask[index, width-len(row):] = 1
        return ids, mask


@dataclass(frozen=True)
class QwenTextChunk:
    content: str
    input_text: str
    start: int
    end: int
    token_count: int


def prepare_qwen_chunks(tokenizer: Any, title: str, body: str,
                        budget: int = MAX_INPUT_TOKENS) -> list[QwenTextChunk]:
    """Same natural-sentence packing used by the full-corpus local comparison.

    Include at most 64 title tokens, overlap at most one 64-token sentence, and
    split overlong sentences by source character positions. Never drop a tail.
    """
    title_ids = tokenizer.encode(title, add_special_tokens=False)
    prefix = tokenizer.decode(title_ids[:64]) + '\n\n' if title else ''
    boundaries = sorted({0, len(body), *(m.end() for m in re.finditer(r'[。！？]|[.!?](?:\s|$)|\n+', body))})
    start = 0
    chunks: list[QwenTextChunk] = []
    while start < len(body):
        low, high, best = start + 1, len(body), start
        while low <= high:
            middle = (low + high) // 2
            count = len(tokenizer.encode(prefix + body[start:middle]))
            if count <= budget:
                best, low = middle, middle + 1
            else:
                high = middle - 1
        if best == start:
            raise ValueError('No source character fits the token budget.')
        natural = [end for end in boundaries if start < end <= best and end >= start + (best-start)//2]
        end = natural[-1] if natural else best
        source = body[start:end]
        input_text = prefix + source
        tokens = len(tokenizer.encode(input_text))
        if tokens > budget:
            raise ValueError('Prepared source exceeds the input token budget.')
        chunks.append(QwenTextChunk(source, input_text, start, end, tokens))
        if end == len(body):
            break
        overlap = [value for value in boundaries if start < value < end]
        next_start = overlap[-1] if overlap else end
        if len(tokenizer.encode(body[next_start:end], add_special_tokens=False)) > 64:
            next_start = end
        start = next_start
    return chunks


class QwenEmbeddingProvider:
    """Same service-facing interface as LocalEmbeddingProvider, all CPU/offline."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any = None
        self._tokenizer: Any = None
        self._available = settings.semantic_search_enabled
        self._last_error: str | None = None
        self._failed_at = 0.0
        self._lock = threading.RLock()
        self._query_cache: dict[str, tuple[float, ...]] = {}

    @property
    def model_name(self) -> str:
        return self.settings.semantic_model_name

    @property
    def expected_dimensions(self) -> int:
        return self.settings.semantic_embedding_dimensions

    @property
    def available(self) -> bool:
        return self.settings.semantic_search_enabled and (
            self._available or time.monotonic()-self._failed_at >= self.settings.semantic_retry_interval_seconds)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _record_failure(self, exc: Exception) -> None:
        self._last_error = str(exc)
        self._available = False
        self._failed_at = time.monotonic()

    def preload(self) -> None:
        if not self.available:
            return
        try:
            with self._lock:
                self._load_model()
                self._available = True
                self._last_error = None
        except Exception as exc:
            self._record_failure(exc)
            raise

    def _resolve_model_path(self) -> Path:
        directory = self.settings.semantic_model_dir
        if (directory / 'config.json').is_file():
            manifest_path = directory / 'reader-model.json'
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text())
                if not isinstance(manifest, dict) or (
                    manifest.get('model_name') != self.model_name
                    or manifest.get('revision') != MODEL_REVISION
                ):
                    raise ValueError('Local Qwen model identity does not match the configured model/revision.')
            return directory
        raise RuntimeError(f'Local Qwen model files are missing from {directory}.')

    @serialized_model_load
    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self.model_name != MODEL_NAME:
            raise ValueError(f'Qwen provider requires model {MODEL_NAME}.')
        if not 32 <= self.expected_dimensions <= 1024:
            raise ValueError('Qwen embedding dimensions must be between 32 and 1024.')
        directory = self._resolve_model_path()
        if not (directory / ONNX_FILE).is_file():
            raise RuntimeError(f'Local Qwen ONNX model is missing from {directory}.')
        from tokenizers import Tokenizer  # type: ignore[import-untyped]

        tokenizer = QwenTokenizer(Tokenizer.from_file(str(directory / 'tokenizer.json')))
        model = onnx_session(directory / ONNX_FILE, self.settings.search_cpu_threads)
        self._tokenizer, self._model = tokenizer, model
        release_unused_memory()
        return model

    def prepare_embedding_chunks(self, title: str, text: str) -> tuple[list[str], list[str]]:
        try:
            with self._lock:
                self._load_model()
                chunks = prepare_qwen_chunks(self._tokenizer, title, text)
            return [chunk.content for chunk in chunks], [chunk.input_text for chunk in chunks]
        except Exception as exc:
            self._record_failure(exc)
            raise

    def _encode(self, texts: list[str]) -> list[list[float]]:
        import numpy as np

        model = self._load_model()
        vectors: list[list[float]] = []
        # Bound memory independently of a caller's indexing batch size.
        for offset in range(0, len(texts), 4):
            ids, mask = self._tokenizer.pad_batch(texts[offset:offset+4])
            if ids.shape[1] > MAX_INPUT_TOKENS:
                raise ValueError('Embedding input exceeds 512 tokens; prepare source chunks first.')
            # Left padding makes the last position the last source token.
            hidden = model.run(['last_hidden_state'], {'input_ids': ids, 'attention_mask': mask})[0]
            hidden = hidden[:, -1, :self.expected_dimensions].astype(np.float32)
            norms = np.maximum(np.linalg.norm(hidden, axis=1, keepdims=True), 1e-12)
            vectors.extend((hidden / norms).tolist())
        for vector in vectors:
            self.validate_dimensions(vector)
        return vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or not self.available:
            return []
        try:
            with self._lock:
                vectors = self._encode(texts)
                self._available = True
                self._last_error = None
                return vectors
        except ValueError:
            # An invalid caller input is not a model outage for other searches.
            raise
        except Exception as exc:
            self._record_failure(exc)
            raise

    def embed_query(self, query: str) -> tuple[float, ...]:
        cached = self._query_cache.get(query)
        if cached is not None:
            return cached
        if not self._lock.acquire(timeout=max(0, self.settings.semantic_query_lock_timeout_seconds)):
            raise RuntimeError('Semantic search is busy; keyword results remain available.')
        try:
            if self._model is None:
                raise RuntimeError('Semantic model is preparing; keyword results remain available.')
            if query in self._query_cache:
                return self._query_cache[query]
            vectors = self.embed([f'Instruct: {QUERY_INSTRUCTION}\nQuery:{query}'])
            if len(vectors) != 1:
                raise RuntimeError('Query embedding was not generated.')
            if len(self._query_cache) >= 128:
                self._query_cache.pop(next(iter(self._query_cache)))
            result = tuple(vectors[0])
            self._query_cache[query] = result
            return result
        finally:
            self._lock.release()

    def validate_dimensions(self, vector: list[float]) -> None:
        if len(vector) != self.expected_dimensions:
            raise ValueError(f'Embedding dimensions mismatch: expected {self.expected_dimensions}, got {len(vector)}.')
