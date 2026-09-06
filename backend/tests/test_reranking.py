from __future__ import annotations

import json
import threading
import time
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.reranking import (
    LocalRerankerProvider,
    RerankerBusyError,
    RerankerInferenceError,
    RerankerInputError,
    RerankerUnavailableError,
)


class FakeTensor:
    def __init__(self, values, shape=None):
        self.values = values
        self.shape = shape or (len(values), 1)
        self.devices = []

    def to(self, device):
        self.devices.append(device)
        return self

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def reshape(self, _):
        return self

    def tolist(self):
        return self.values


class FakeTokenizer:
    def __init__(self):
        self.calls = []
        self.tensors = []

    def encode(self, query, passage, **options):
        assert options == {"add_special_tokens": True, "truncation": False}
        return [0] * (len(query) + len(passage) + 4)

    def __call__(self, pairs, **options):
        self.calls.append((pairs, options))
        tensor = FakeTensor([float(passage) for _, passage in pairs])
        self.tensors.append(tensor)
        return {"input_ids": tensor}


class FakeModel:
    def __init__(self):
        self.device = None
        self.evaluating = False
        self.calls = 0
        self.override = None

    def to(self, device):
        self.device = device
        return self

    def eval(self):
        self.evaluating = True
        return self

    def __call__(self, **inputs):
        self.calls += 1
        if isinstance(self.override, Exception):
            raise self.override
        return SimpleNamespace(logits=self.override or inputs["input_ids"])


@pytest.fixture
def runtime(monkeypatch):
    import sys

    monkeypatch.setattr("app.reranking.platform.machine", lambda: "aarch64")
    tokenizer, model = FakeTokenizer(), FakeModel()
    loads, thread_counts, quantizations = [], [], []
    quantized_backend = SimpleNamespace(supported_engines=["x86"], engine="none")
    linear_class = type("Linear", (), {})

    def quantize(model, modules, dtype):
        quantizations.append((model, modules, dtype, quantized_backend.engine))
        return model

    def tokenizer_load(name, **kwargs):
        loads.append(("tokenizer", name, kwargs))
        return tokenizer

    def model_load(name, **kwargs):
        loads.append(("model", name, kwargs))
        return model

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        float32="float32", set_num_threads=thread_counts.append, inference_mode=nullcontext,
        qint8="qint8", backends=SimpleNamespace(quantized=quantized_backend),
        nn=SimpleNamespace(Linear=linear_class),
        ao=SimpleNamespace(quantization=SimpleNamespace(quantize_dynamic=quantize)),
    ))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=tokenizer_load),
        AutoModelForSequenceClassification=SimpleNamespace(from_pretrained=model_load),
    ))
    return SimpleNamespace(tokenizer=tokenizer, model=model, loads=loads, threads=thread_counts,
        quantizations=quantizations, quantized_backend=quantized_backend, linear_class=linear_class)


def test_queries_never_load_and_preload_enforces_cpu_and_cache_settings(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path, revision="fixed-revision", num_threads=2)
    assert not provider.available
    assert not provider.ready
    with pytest.raises(RerankerUnavailableError, match="preparing"):
        provider.score("query", ["1"])
    assert runtime.loads == []
    provider.preload()
    assert provider.available and provider.ready
    assert runtime.model.device == "cpu"
    assert runtime.model.evaluating
    assert runtime.threads == [provider.num_threads]
    for _, name, options in runtime.loads:
        assert name == "BAAI/bge-reranker-v2-m3"
        assert options["revision"] == "fixed-revision"
        assert options["cache_dir"] == str(tmp_path)
        assert options["local_files_only"] is True
        assert options["trust_remote_code"] is False
    assert runtime.loads[1][2]["torch_dtype"] == "float32"


def test_scores_align_after_batching_deduplication_and_cache_hits(tmp_path, runtime):
    provider = LocalRerankerProvider(cache_dir=tmp_path, batch_size=2, max_length=128)
    provider.preload()
    assert provider.score("query", ["3", "1", "3", "2", "4"]) == [3, 1, 3, 2, 4]
    assert runtime.model.calls == 2
    assert provider.score("query", ["4", "1", "3"]) == [4, 1, 3]
    assert runtime.model.calls == 2
    assert provider.score("other query", ["3"]) == [3]
    assert runtime.model.calls == 3
    for pairs, options in runtime.tokenizer.calls:
        assert len(pairs) <= 2
        assert options == {"padding": True, "truncation": False, "return_tensors": "pt"}
    assert all(tensor.devices == ["cpu"] for tensor in runtime.tokenizer.tensors)


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
    for _, source, options in runtime.loads:
        assert source == str(tmp_path)
        assert options["local_files_only"] is True
        assert options["revision"] == "pinned-revision"
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


@pytest.mark.parametrize("logits", [FakeTensor([float("nan")]), FakeTensor([float("inf")]), FakeTensor([1, 2], (1, 2))])
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
        assert len(runtime.tokenizer.encode("很长的问题", chunk, add_special_tokens=True, truncation=False)) <= 32
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


@pytest.mark.parametrize(("architecture", "requested", "effective"), [
    ("x86_64", "auto", "int8"), ("AMD64", "auto", "int8"),
    ("aarch64", "auto", "none"), ("x86_64", "none", "none"),
    ("x86_64", "int8", "int8"),
])
def test_quantization_selection_is_explicit_cpu_only_and_reported(tmp_path, runtime, monkeypatch, architecture, requested, effective):
    monkeypatch.setattr("app.reranking.platform.machine", lambda: architecture)
    provider = LocalRerankerProvider(cache_dir=tmp_path, quantization=requested)
    provider.preload()
    assert provider.effective_quantization == effective
    assert provider.metadata["effective_quantization"] == effective
    assert provider.metadata["quantization"] == requested
    assert provider.metadata["device"] == runtime.model.device == "cpu"
    assert len(runtime.quantizations) == (1 if effective == "int8" else 0)
    if effective == "int8":
        assert runtime.quantizations[0] == (runtime.model, {runtime.linear_class}, "qint8", "x86")
        assert provider.quantization_engine == "x86"
    provider.preload()
    assert len(runtime.quantizations) == (1 if effective == "int8" else 0)


@pytest.mark.parametrize("architecture", ["aarch64", "x86_64"])
def test_unsupported_explicit_int8_fails_without_silent_fp32_fallback(tmp_path, runtime, monkeypatch, architecture):
    monkeypatch.setattr("app.reranking.platform.machine", lambda: architecture)
    runtime.quantized_backend.supported_engines = ["qnnpack"]
    provider = LocalRerankerProvider(cache_dir=tmp_path, quantization="int8")
    with pytest.raises(RerankerUnavailableError, match="x86 quantization engine"):
        provider.preload()
    assert not provider.available and provider.error
    assert provider.effective_quantization is None
    assert not runtime.loads


def test_pair_cache_identity_includes_quantization_configuration(tmp_path, runtime, monkeypatch):
    monkeypatch.setattr("app.reranking.platform.machine", lambda: "x86_64")
    full = LocalRerankerProvider(cache_dir=tmp_path, quantization="none")
    quantized = LocalRerankerProvider(cache_dir=tmp_path, quantization="auto")
    full.preload()
    quantized.preload()
    assert full._cache_key("q", "passage") != quantized._cache_key("q", "passage")


def test_auto_uses_fp32_when_x86_quantization_engine_is_unavailable(tmp_path, runtime, monkeypatch):
    monkeypatch.setattr("app.reranking.platform.machine", lambda: "x86_64")
    runtime.quantized_backend.supported_engines = ["qnnpack"]
    provider = LocalRerankerProvider(cache_dir=tmp_path, quantization="auto")
    provider.preload()
    assert provider.available and provider.error is None
    assert provider.metadata["quantization"] == "auto"
    assert provider.metadata["effective_quantization"] == "none"
    assert provider.quantization_engine is None
    assert not runtime.quantizations
    assert provider.score("q", ["1"]) == [1]
