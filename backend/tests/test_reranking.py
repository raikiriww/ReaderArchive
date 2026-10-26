from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from app.reranking import (
    LocalRerankerProvider,
    RerankerBusyError,
    RerankerInferenceError,
    RerankerInputError,
    RerankerUnavailableError,
)

QUERY_END, PASSAGE_END, PAD = 2, 3, 0


class FakeTokenizer:
    """Pair ids are [1, query..., 2, passage..., 3], so the session can read passages back."""

    def __init__(self):
        self.calls = []

    def no_truncation(self):
        pass

    def no_padding(self):
        pass

    def token_to_id(self, token):
        return PAD if token == "<pad>" else None

    def encode(self, query, passage, add_special_tokens=True):
        assert add_special_tokens is True
        self.calls.append((query, passage))
        return SimpleNamespace(ids=[1, *map(ord, query), QUERY_END, *map(ord, passage), PASSAGE_END])


class FakeSession:
    def __init__(self):
        self.calls = 0
        self.feeds = []
        self.override = None

    def run(self, outputs, feeds):
        assert outputs == ["logits"]
        self.calls += 1
        self.feeds.append(feeds)
        if isinstance(self.override, Exception):
            raise self.override
        if self.override is not None:
            return [self.override]
        scores = []
        for ids, mask in zip(feeds["input_ids"], feeds["attention_mask"], strict=True):
            row = [int(value) for value, keep in zip(ids, mask, strict=True) if keep]
            passage = row[row.index(QUERY_END) + 1:row.index(PASSAGE_END)]
            scores.append([float("".join(map(chr, passage)))])
        return [np.array(scores, dtype=np.float32)]


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    import sys

    (tmp_path / "model.onnx").write_bytes(b"onnx")
    (tmp_path / "tokenizer.json").write_text("{}")
    tokenizer, model = FakeTokenizer(), FakeSession()
    loads, threads = [], []

    def tokenizer_load(path):
        loads.append(("tokenizer", path))
        return tokenizer

    def session(path, num_threads):
        loads.append(("model", str(path)))
        threads.append(num_threads)
        return model

    monkeypatch.setitem(sys.modules, "tokenizers", SimpleNamespace(Tokenizer=SimpleNamespace(from_file=tokenizer_load)))
    monkeypatch.setattr("app.reranking.onnx_session", session)
    return SimpleNamespace(tokenizer=tokenizer, model=model, loads=loads, threads=threads)


def test_queries_never_load_and_preload_enforces_cpu_and_cache_settings(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path, revision="fixed-revision", num_threads=2)
    assert not provider.available
    assert not provider.ready
    with pytest.raises(RerankerUnavailableError, match="preparing"):
        provider.score("query", ["1"])
    assert runtime.loads == []
    provider.preload()
    assert provider.available and provider.ready
    assert runtime.threads == [provider.num_threads]
    assert runtime.loads == [("tokenizer", str(tmp_path / "tokenizer.json")), ("model", str(tmp_path / "model.onnx"))]


def test_scores_align_after_batching_deduplication_and_cache_hits(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path, batch_size=2, max_length=128)
    provider.preload()
    assert provider.score("query", ["3", "1", "3", "2", "4"]) == [3, 1, 3, 2, 4]
    assert runtime.model.calls == 2
    assert provider.score("query", ["4", "1", "3"]) == [4, 1, 3]
    assert runtime.model.calls == 2
    assert provider.score("other query", ["3"]) == [3]
    assert runtime.model.calls == 3
    assert all(len(feeds["input_ids"]) <= 2 for feeds in runtime.model.feeds)


def test_standalone_image_snapshot_loads_offline_without_changing_identity(tmp_path, runtime):
    (tmp_path / "config.json").write_text("{}")
    provider = LocalRerankerProvider(cache_dir=tmp_path, revision="pinned-revision")
    # A request during cold start does not attempt to inspect/load/download it.
    with pytest.raises(RerankerUnavailableError, match="preparing"):
        provider.split_passage("query", "passage")
    assert runtime.loads == []
    provider.preload()
    assert provider.model_name == "BAAI/bge-reranker-v2-m3"
    assert provider.revision == "pinned-revision"
    assert all(path.startswith(str(tmp_path)) for _, path in runtime.loads)
    assert provider.score("query", ["3", "1"]) == [3, 1]


@pytest.mark.parametrize("field", ["model_name", "revision"])
def test_image_manifest_mismatch_never_loads_weights(tmp_path, runtime, field):
    manifest = {"model_name": "BAAI/bge-reranker-v2-m3", "revision": "pinned"}
    manifest[field] = "different"
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "reader-model.json").write_text(json.dumps(manifest))
    provider = LocalRerankerProvider(cache_dir=tmp_path, revision="pinned")
    with pytest.raises(RerankerUnavailableError, match="identity"):
        provider.preload()
    assert runtime.loads == []
    assert not provider.ready


def test_matching_image_manifest_loads(tmp_path, runtime):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "reader-model.json").write_text(json.dumps({
        "model_name": "BAAI/bge-reranker-v2-m3", "revision": "pinned"}))
    provider = LocalRerankerProvider(cache_dir=tmp_path, revision="pinned")
    provider.preload()
    assert provider.ready
    assert len(runtime.loads) == 2


def test_lru_has_fixed_capacity_and_returns_all_scores_when_request_exceeds_cache(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path, cache_size=2)
    provider.preload()
    assert provider.score("q", ["1", "2", "3", "4"]) == [1, 2, 3, 4]
    assert len(provider._scores) == 2
    calls = runtime.model.calls
    assert provider.score("q", ["3", "4"]) == [3, 4]
    assert runtime.model.calls == calls
    assert provider.score("q", ["1"]) == [1]
    assert runtime.model.calls == calls + 1
    assert len(provider._scores) == 2


@pytest.mark.parametrize("logits", [np.array([[np.nan]]), np.array([[np.inf]]), np.array([[1.0, 2.0]])])
def test_invalid_outputs_are_errors_and_do_not_populate_cache(tmp_path, runtime, logits):
    provider = LocalRerankerProvider(cache_dir=tmp_path)
    provider.preload()
    runtime.model.override = logits
    with pytest.raises(RerankerInferenceError):
        provider.score("q", ["1"])
    assert provider.last_error
    assert not provider.available
    assert not provider._scores


def test_later_batch_failure_does_not_publish_partial_scores(tmp_path, runtime, monkeypatch):
    provider = LocalRerankerProvider(cache_dir=tmp_path, batch_size=1)
    provider.preload()
    attempts = []

    def score_batch(query, passages):
        attempts.append(passages)
        if len(attempts) == 2:
            raise RuntimeError("CPU allocation failed")
        return [1.0]

    monkeypatch.setattr(provider, "_score_batch", score_batch)
    with pytest.raises(RerankerInferenceError, match="CPU allocation failed"):
        provider.score("q", ["1", "2"])
    assert not provider._scores


def test_load_failure_is_retryable_after_cooldown(tmp_path, runtime, monkeypatch):
    provider = LocalRerankerProvider(cache_dir=tmp_path, retry_delay_seconds=60)
    now = [100.0]
    monkeypatch.setattr("app.reranking.time.monotonic", lambda: now[0])
    original_load = provider._load_model
    attempts = []

    def load():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("incomplete model cache")
        original_load()

    monkeypatch.setattr(provider, "_load_model", load)
    with pytest.raises(RerankerUnavailableError, match="incomplete model cache"):
        provider.preload()
    assert provider.error == "incomplete model cache"
    with pytest.raises(RerankerUnavailableError, match="waiting to retry"):
        provider.preload()
    assert len(attempts) == 1
    now[0] += 61
    provider.preload()
    assert provider.available and provider.error is None
    assert provider.score("q", ["2"]) == [2]


def test_inference_failure_is_not_empty_success_and_can_retry(tmp_path, runtime, monkeypatch):
    provider = LocalRerankerProvider(cache_dir=tmp_path, retry_delay_seconds=60)
    now = [1.0]
    monkeypatch.setattr("app.reranking.time.monotonic", lambda: now[0])
    provider.preload()
    runtime.model.override = RuntimeError("inference failed")
    with pytest.raises(RerankerInferenceError, match="inference failed"):
        provider.score("q", ["1"])
    runtime.model.override = None
    with pytest.raises(RerankerUnavailableError):
        provider.score("q", ["1"])
    now[0] += 61
    assert provider.score("q", ["1"]) == [1]
    assert provider.available and provider.error is None


def test_busy_model_fails_fast_without_poisoning_readiness(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path)
    provider.preload()
    locked = threading.Event()
    release = threading.Event()

    def hold_lock():
        with provider._lock:
            locked.set()
            release.wait(2)

    worker = threading.Thread(target=hold_lock)
    worker.start()
    assert locked.wait(1)
    try:
        started = time.monotonic()
        with pytest.raises(RerankerBusyError):
            provider.score("q", ["1"])
        assert time.monotonic() - started < 0.2
        assert provider.available and provider.error is None
        with pytest.raises(RerankerBusyError):
            provider.preload()
        with pytest.raises(RerankerBusyError):
            provider.split_passage("q", "正文")
    finally:
        release.set()
        worker.join(2)
    assert provider.score("q", ["1"]) == [1]


def test_bounds_empty_input_and_disabled_provider(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path, max_passages=1)
    assert provider.score("q", []) == []
    with pytest.raises(ValueError, match="At most"):
        provider.score("q", ["1", "2"])
    with pytest.raises(ValueError):
        provider.score("", ["1"])
    assert not runtime.loads
    disabled = LocalRerankerProvider(cache_dir=tmp_path, enabled=False)
    with pytest.raises(RerankerUnavailableError, match="disabled"):
        disabled.preload()
    with pytest.raises(RerankerUnavailableError, match="disabled"):
        disabled.score("q", ["1"])
    for settings in ({"batch_size": 0}, {"num_threads": 100}, {"max_length": 8193}, {"lock_timeout_seconds": 1}, {"cache_size": -1}):
        with pytest.raises(ValueError):
            LocalRerankerProvider(cache_dir=tmp_path, **settings)


def test_splitting_preserves_every_source_character_and_pair_token_budget(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path, max_length=32)
    with pytest.raises(RerankerUnavailableError):
        provider.split_passage("query", "正文")
    provider.preload()
    text = "".join(f"📚第{index:03d}项铺垫。" for index in range(30)) + "结尾的真正答案！"
    chunks = provider.split_passage("很长的问题", text)
    assert len(chunks) > 1 and chunks[-1].endswith("结尾的真正答案！")
    cursor = 0
    previous_start = -1
    for chunk in chunks:
        assert len(runtime.tokenizer.encode("很长的问题", chunk).ids) <= 32
        start = text.find(chunk, previous_start + 1)
        assert 0 <= start <= cursor
        cursor = start + len(chunk)
        previous_start = start
    assert cursor == len(text)
    assert runtime.model.calls == 0


def test_oversized_inputs_are_rejected_without_inference_truncation_or_cooldown(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path, max_length=16)
    provider.preload()
    with pytest.raises(RerankerInputError, match="split_passage"):
        provider.score("q", ["1" * 20])
    assert runtime.model.calls == 0
    assert provider.available and provider.error is None
    with pytest.raises(RerankerInputError, match="one source character"):
        provider.split_passage("q" * 30, "正文")
    assert provider.available
    assert provider.score("q", ["1"]) == [1]


def test_onnx_int8_model_is_reported_and_keys_the_score_cache(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path)
    assert provider.effective_quantization is None
    provider.preload()
    assert provider.metadata["quantization"] == provider.metadata["effective_quantization"] == "int8"
    assert provider.metadata["quantization_engine"] == "onnxruntime"
    assert provider.metadata["device"] == "cpu"
    assert "int8:int8:onnxruntime" in provider._cache_key("q", "passage")


@pytest.mark.parametrize("missing", ["model.onnx", "tokenizer.json"])
def test_missing_model_files_fail_retryably_without_loading(tmp_path, runtime, missing):
    (tmp_path / missing).unlink()
    provider = LocalRerankerProvider(cache_dir=tmp_path)
    with pytest.raises(RerankerUnavailableError, match="missing"):
        provider.preload()
    assert not provider.ready and provider.error
    assert runtime.loads == []


def test_pairs_are_right_padded_with_an_attention_mask(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path, batch_size=2)
    provider.preload()
    assert provider.score("q", ["7", "123"]) == [7, 123]
    feeds = runtime.model.feeds[0]
    assert feeds["input_ids"].dtype == feeds["attention_mask"].dtype == np.int64
    assert feeds["attention_mask"].tolist() == [[1, 1, 1, 1, 1, 0, 0], [1] * 7]
    assert feeds["input_ids"][0].tolist()[-2:] == [PAD, PAD]


def test_idle_unload_frees_the_model_and_a_requested_reload_keeps_scores(tmp_path, runtime, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.reranking.time.monotonic", lambda: clock[0])
    trims = []
    monkeypatch.setattr("app.reranking.release_unused_memory", lambda: trims.append(True))
    provider = LocalRerankerProvider(cache_dir=tmp_path)
    provider.request_load()
    assert provider.load_requested
    provider.preload()
    assert provider.ready and not provider.load_requested
    # A loaded model ignores reload requests.
    provider.request_load()
    assert not provider.load_requested
    clock[0] += 50
    assert provider.score("q", ["1", "2"]) == [1, 2]
    clock[0] += 299
    assert not provider.unload_if_idle(300)
    assert provider.ready
    clock[0] += 1
    trims.clear()
    assert provider.unload_if_idle(300)
    assert not provider.ready and not provider.available and trims == [True]
    assert not provider.unload_if_idle(300)
    with pytest.raises(RerankerUnavailableError, match="preparing"):
        provider.score("q", ["1"])
    provider.request_load()
    assert provider.load_requested
    provider.preload()
    assert provider.ready and not provider.load_requested
    calls = runtime.model.calls
    assert provider.score("q", ["1", "2"]) == [1, 2]
    assert runtime.model.calls == calls
    assert [kind for kind, _ in runtime.loads].count("model") == 2


def test_idle_unload_skips_a_busy_model_and_disabled_providers_ignore_requests(tmp_path, runtime, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.reranking.time.monotonic", lambda: clock[0])
    provider = LocalRerankerProvider(cache_dir=tmp_path)
    provider.preload()
    clock[0] += 1000
    provider._lock.acquire()
    try:
        assert not provider.unload_if_idle(1)
    finally:
        provider._lock.release()
    assert provider.ready
    disabled = LocalRerankerProvider(cache_dir=tmp_path, enabled=False)
    disabled.request_load()
    assert not disabled.load_requested


def test_preload_returns_freed_load_memory(tmp_path, runtime, monkeypatch):
    trims = []
    monkeypatch.setattr("app.reranking.release_unused_memory", lambda: trims.append(True))
    LocalRerankerProvider(cache_dir=tmp_path).preload()
    assert trims == [True]
