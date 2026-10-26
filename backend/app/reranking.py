"""A bounded, CPU-only cross-encoder with explicit readiness and failure states.

The image ships BAAI's tokenizer and onnx-community's int8 ONNX export, run by
onnxruntime. Importing this module loads neither. Call ``preload`` in a
background worker before using ``score`` on a request thread. A worker may also
``unload_if_idle`` to free the model, and reload it after ``request_load``. Scores are raw
single-label logits; callers must not interpret them as calibrated probabilities.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from app.model_runtime import onnx_session, release_unused_memory, serialized_model_load

ONNX_FILE = "model.onnx"


class RerankerError(RuntimeError):
    """Reranking was not completed; callers may explicitly fall back to retrieval."""


class RerankerBusyError(RerankerError):
    """Another model load or scoring operation already holds the CPU budget."""


class RerankerUnavailableError(RerankerError):
    """The model is disabled, not preloaded, or cooling down after a failure."""


class RerankerInputError(RerankerError, ValueError):
    """An input exceeds the explicit token budget and must be split first."""


class RerankerInferenceError(RerankerError):
    """The model failed to produce one finite score for every input passage."""


class LocalRerankerProvider:
    def __init__(
        self,
        *,
        cache_dir: Path | str,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        revision: str | None = None,
        num_threads: int = 2,
        batch_size: int = 2,
        max_length: int = 512,
        max_passages: int = 400,
        cache_size: int = 1024,
        lock_timeout_seconds: float = 0.0,
        retry_delay_seconds: float = 60.0,
        enabled: bool = True,
    ) -> None:
        for name, value, maximum in (
            ("num_threads", num_threads, 64),
            ("batch_size", batch_size, 32),
            ("max_length", max_length, 8192),
            ("max_passages", max_passages, 4096),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer between 1 and {maximum}.")
        if max_length < 16:
            raise ValueError("max_length must allow at least 16 tokens.")
        if isinstance(cache_size, bool) or not isinstance(cache_size, int) or not 0 <= cache_size <= 4096:
            raise ValueError("cache_size must be between 0 and 4096.")
        if not math.isfinite(lock_timeout_seconds) or not 0 <= lock_timeout_seconds <= 0.25:
            raise ValueError("lock_timeout_seconds must be between 0 and 0.25.")
        if not math.isfinite(retry_delay_seconds) or retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be finite and nonnegative.")
        if not model_name.strip():
            raise ValueError("model_name must not be empty.")
        self.model_name = model_name
        self.revision = revision
        self.cache_dir = Path(cache_dir)
        self.num_threads = min(num_threads, os.cpu_count() or 1)
        self.batch_size = batch_size
        self.max_length = max_length
        self.max_passages = max_passages
        self.cache_size = cache_size
        self.lock_timeout_seconds = lock_timeout_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self.enabled = enabled
        # The shipped model is quantized; these feed diagnostics and cache keys.
        self.quantization = "int8"
        self.effective_quantization: str | None = None
        self.quantization_engine: str | None = None
        self._model: Any = None
        self._tokenizer: Any = None
        self._pad_id = 0
        self._lock = threading.Lock()
        self._scores: OrderedDict[tuple[str, str | None, int, str, str], float] = OrderedDict()
        self._last_error: str | None = None
        self._failed_at: float | None = None
        self._last_used = time.monotonic()
        self._load_requested = False

    @property
    def ready(self) -> bool:
        return self.enabled and self._model is not None and self._tokenizer is not None

    @property
    def available(self) -> bool:
        return self.ready and not self._cooling_down()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def load_requested(self) -> bool:
        return self._load_requested

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_used

    @property
    def error(self) -> str | None:
        return self._last_error

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name, "revision": self.revision, "device": "cpu",
            "num_threads": self.num_threads, "batch_size": self.batch_size,
            "max_length": self.max_length, "quantization": self.quantization,
            "effective_quantization": self.effective_quantization,
            "quantization_engine": self.quantization_engine,
        }

    def _cooling_down(self) -> bool:
        return (
            self._failed_at is not None
            and time.monotonic() - self._failed_at < self.retry_delay_seconds
        )

    def _acquire(self) -> None:
        if not self._lock.acquire(timeout=self.lock_timeout_seconds):
            raise RerankerBusyError("CPU reranker is busy; reranking was not performed.")

    def _check_enabled(self) -> None:
        if not self.enabled:
            raise RerankerUnavailableError("CPU reranker is disabled.")
        if self._cooling_down():
            raise RerankerUnavailableError("CPU reranker is waiting to retry after a failure.")

    def _record_failure(self, error: Exception) -> None:
        self._last_error = str(error) or type(error).__name__
        self._failed_at = time.monotonic()

    def preload(self) -> None:
        """Load on the calling worker, with a retry window after load failures."""
        self._check_enabled()
        self._acquire()
        try:
            self._check_enabled()
            if not self.ready:
                self._load_model()
                self._last_used = time.monotonic()
            self._load_requested = False
            self._last_error = None
            self._failed_at = None
        except RerankerUnavailableError:
            raise
        except Exception as exc:
            self._model = self._tokenizer = None
            self._scores.clear()
            self.effective_quantization = self.quantization_engine = None
            self._record_failure(exc)
            raise RerankerUnavailableError(f"CPU reranker could not be loaded: {exc}") from exc
        finally:
            self._lock.release()

    def request_load(self) -> None:
        """Ask the background worker to reload an unloaded model; never loads here."""
        if self.enabled and not self.ready:
            self._load_requested = True

    def unload_if_idle(self, idle_seconds: float) -> bool:
        """Drop the model once unused for ``idle_seconds``; skip while it is busy."""
        if not self.ready or self.idle_seconds < idle_seconds:
            return False
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if not self.ready or self.idle_seconds < idle_seconds:
                return False
            # Scores stay cached: a reload yields the same model and settings.
            self._model = self._tokenizer = None
        finally:
            self._lock.release()
        release_unused_memory()
        return True

    @serialized_model_load
    def _load_model(self) -> None:
        manifest_path = self.cache_dir / "reader-model.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text())
            if not isinstance(manifest, dict) or (
                manifest.get("model_name") != self.model_name
                or manifest.get("revision") != self.revision
            ):
                raise ValueError("Local reranker model identity does not match the configured model/revision.")
        model_path = self.cache_dir / ONNX_FILE
        tokenizer_path = self.cache_dir / "tokenizer.json"
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise RuntimeError(f"Local reranker ONNX model or tokenizer is missing from {self.cache_dir}.")
        from tokenizers import Tokenizer  # type: ignore[import-untyped]

        tokenizer = Tokenizer.from_file(str(tokenizer_path))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        pad_id = tokenizer.token_to_id("<pad>")
        if pad_id is None:
            raise ValueError("Reranker tokenizer has no <pad> token.")
        model = onnx_session(model_path, self.num_threads)
        # Publish only a fully initialized pair. A failed load can be retried.
        self._tokenizer, self._model, self._pad_id = tokenizer, model, int(pad_id)
        self.effective_quantization = "int8"
        self.quantization_engine = "onnxruntime"
        release_unused_memory()

    def _pair_size(self, query: str, passage: str) -> int:
        return len(self._tokenizer.encode(query, passage, add_special_tokens=True).ids)

    def split_passage(self, query: str, text: str) -> list[str]:
        """Cover every source character using measured, overlapping pair inputs.

        No model loading or inference occurs here. The tokenizer clone has no
        truncation, so query tokens and pair special tokens count in full.
        """
        if not isinstance(query, str) or not query.strip() or not isinstance(text, str):
            raise ValueError("query must be nonempty and text must be a string.")
        self._check_enabled()
        self._acquire()
        try:
            self._check_enabled()
            if not self.ready:
                raise RerankerUnavailableError("CPU reranker is preparing; passage splitting was not performed.")
            if not text:
                return []
            chunks: list[str] = []
            start = 0
            while start < len(text):
                low, high, best = start + 1, min(len(text), start + self.max_length * 12), start
                while low <= high:
                    end = (low + high) // 2
                    if self._pair_size(query, text[start:end]) <= self.max_length:
                        best = end
                        low = end + 1
                    else:
                        high = end - 1
                if best == start:
                    raise RerankerInputError("Reranker token budget cannot fit the query and one source character.")
                chunks.append(text[start:best])
                if best == len(text):
                    break
                start = max(start + 1, best - min(16, (best - start) // 5))
            return chunks
        finally:
            self._lock.release()

    def _cache_key(self, query: str, passage: str) -> tuple[str, str | None, int, str, str]:
        query_bytes = query.encode("utf-8")
        digest = hashlib.sha256(len(query_bytes).to_bytes(8, "big") + query_bytes)
        digest.update(passage.encode("utf-8"))
        return self.model_name, self.revision, self.max_length, (
            f"{self.quantization}:{self.effective_quantization}:{self.quantization_engine}"), digest.hexdigest()

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Return aligned raw logits, or raise; never load/download in a query."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a nonempty string.")
        if not isinstance(passages, list) or any(not isinstance(value, str) for value in passages):
            raise ValueError("passages must be a list of strings.")
        if len(passages) > self.max_passages:
            raise ValueError(f"At most {self.max_passages} passages may be scored per call.")
        if not passages:
            return []
        self._check_enabled()
        self._acquire()
        try:
            self._check_enabled()
            if not self.ready:
                raise RerankerUnavailableError("CPU reranker is preparing; reranking was not performed.")
            self._last_used = time.monotonic()
            keys = [self._cache_key(query, passage) for passage in passages]
            resolved: dict[tuple[str, str | None, int, str, str], float] = {}
            missing: dict[tuple[str, str | None, int, str, str], str] = {}
            for key, passage in zip(keys, passages, strict=True):
                if key in self._scores:
                    resolved[key] = self._scores[key]
                    self._scores.move_to_end(key)
                elif key not in missing:
                    missing[key] = passage
            pending = list(missing.items())
            new_scores: dict[tuple[str, str | None, int, str, str], float] = {}
            for start in range(0, len(pending), self.batch_size):
                batch = pending[start : start + self.batch_size]
                values = self._score_batch(query, [passage for _, passage in batch])
                if len(values) != len(batch) or any(not math.isfinite(value) for value in values):
                    raise ValueError("Reranker must return one finite score per passage.")
                new_scores.update(zip((key for key, _ in batch), values, strict=True))
            resolved.update(new_scores)
            # Publish cache entries only after every batch validates successfully.
            for key, value in new_scores.items():
                self._scores[key] = value
                while len(self._scores) > self.cache_size:
                    self._scores.popitem(last=False)
            self._last_error = None
            self._failed_at = None
            return [resolved[key] for key in keys]
        except (RerankerUnavailableError, RerankerInputError):
            raise
        except Exception as exc:
            self._record_failure(exc)
            raise RerankerInferenceError(f"CPU reranker failed: {exc}") from exc
        finally:
            self._lock.release()

    def _score_batch(self, query: str, passages: list[str]) -> list[float]:
        import numpy as np

        rows = [self._tokenizer.encode(query, passage, add_special_tokens=True).ids for passage in passages]
        if any(len(row) > self.max_length for row in rows):
            raise RerankerInputError("Reranker input exceeds the token budget; call split_passage first.")
        width = max(map(len, rows))
        ids = np.full((len(rows), width), self._pad_id, dtype=np.int64)
        mask = np.zeros((len(rows), width), dtype=np.int64)
        for index, row in enumerate(rows):
            ids[index, :len(row)] = row
            mask[index, :len(row)] = 1
        logits = self._model.run(["logits"], {"input_ids": ids, "attention_mask": mask})[0]
        shape = tuple(logits.shape)
        if shape not in ((len(passages),), (len(passages), 1)):
            raise ValueError(f"Unexpected reranker score shape: {shape}.")
        return [float(value) for value in logits.reshape(-1).tolist()]
