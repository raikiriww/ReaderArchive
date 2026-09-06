"""A bounded, CPU-only cross-encoder with explicit readiness and failure states.

Importing this module does not import torch or transformers. Call ``preload`` in a
background worker before using ``score`` on a request thread. Scores are raw
single-label logits; callers must not interpret them as calibrated probabilities.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from app.model_runtime import serialized_model_load


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
        local_files_only: bool = True,
        enabled: bool = True,
        quantization: str = "auto",
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
        if quantization not in {"auto", "none", "int8"}:
            raise ValueError("quantization must be auto, none, or int8.")
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
        self.local_files_only = local_files_only
        self.enabled = enabled
        self.quantization = quantization
        self.effective_quantization: str | None = None
        self.quantization_engine: str | None = None
        self._model: Any = None
        self._tokenizer: Any = None
        self._torch: Any = None
        self._budget_tokenizer: Any = None
        self._lock = threading.Lock()
        self._scores: OrderedDict[tuple[str, str | None, int, str, str], float] = OrderedDict()
        self._last_error: str | None = None
        self._failed_at: float | None = None

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
            self._last_error = None
            self._failed_at = None
        except RerankerUnavailableError:
            raise
        except Exception as exc:
            self._model = self._tokenizer = self._torch = self._budget_tokenizer = None
            self._scores.clear()
            self.effective_quantization = self.quantization_engine = None
            self._record_failure(exc)
            raise RerankerUnavailableError(f"CPU reranker could not be loaded: {exc}") from exc
        finally:
            self._lock.release()

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
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # PyTorch intra-op threading is process-wide. Set the explicit CPU budget
        # once during warmup, rather than constructing an unbounded request pool.
        torch.set_num_threads(self.num_threads)
        architecture = platform.machine().lower()
        use_int8 = self.quantization == "int8" or (
            self.quantization == "auto" and architecture in {"x86_64", "amd64"})
        if use_int8:
            supported = architecture in {"x86_64", "amd64"} and "x86" in torch.backends.quantized.supported_engines
            if not supported and self.quantization == "int8":
                raise RuntimeError("Requested CPU INT8 reranking requires the supported x86 quantization engine.")
            use_int8 = supported
        if use_int8:
            # Quantization engine selection, like thread count, is process-wide.
            # Configure it only during model warmup, never in a query operation.
            torch.backends.quantized.engine = "x86"
        options: dict[str, Any] = {
            "cache_dir": str(self.cache_dir),
            "local_files_only": self.local_files_only,
            "trust_remote_code": False,
        }
        if self.revision is not None:
            options["revision"] = self.revision
        # Images contain one standalone snapshot, rather than an entire Hub
        # cache. Keep the configured model identity for diagnostics/cache keys.
        model_source = str(self.cache_dir) if (self.cache_dir / "config.json").is_file() else self.model_name
        tokenizer = AutoTokenizer.from_pretrained(model_source, **options)
        model = AutoModelForSequenceClassification.from_pretrained(
            model_source, torch_dtype=torch.float32, **options
        )
        model.to("cpu")
        model.eval()
        if use_int8:
            model = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
            model.to("cpu")
            model.eval()
        budget_tokenizer = None
        if getattr(tokenizer, "backend_tokenizer", None) is not None:
            from tokenizers import Tokenizer  # type: ignore[import-untyped]

            budget_tokenizer = Tokenizer.from_str(tokenizer.backend_tokenizer.to_str())
            budget_tokenizer.no_truncation()
            budget_tokenizer.no_padding()
        # Publish only a fully initialized pair. A failed load can be retried.
        self._torch, self._tokenizer, self._model = torch, tokenizer, model
        self._budget_tokenizer = budget_tokenizer
        self.effective_quantization = "int8" if use_int8 else "none"
        self.quantization_engine = "x86" if use_int8 else None

    def _pair_size(self, query: str, passage: str) -> int:
        if self._budget_tokenizer is not None:
            return len(self._budget_tokenizer.encode(query, passage, add_special_tokens=True).ids)
        return len(self._tokenizer.encode(query, passage, add_special_tokens=True, truncation=False))

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
        if any(self._pair_size(query, passage) > self.max_length for passage in passages):
            raise RerankerInputError("Reranker input exceeds the token budget; call split_passage first.")
        encoded = self._tokenizer(
            [[query, passage] for passage in passages],
            padding=True,
            truncation=False,
            return_tensors="pt",
        )
        if int(encoded["input_ids"].shape[-1]) > self.max_length:
            raise RerankerInputError("Tokenizer pair exceeds the token budget; input was not truncated.")
        encoded = {name: value.to("cpu") for name, value in encoded.items()}
        with self._torch.inference_mode():
            logits = self._model(**encoded).logits
        shape = tuple(logits.shape)
        if shape not in ((len(passages),), (len(passages), 1)):
            raise ValueError(f"Unexpected reranker score shape: {shape}.")
        return [float(value) for value in logits.detach().float().cpu().reshape(-1).tolist()]
