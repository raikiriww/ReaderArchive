from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import model_runtime
from app.search import _rerank_candidates
from app.service import ArchiveTaskService


def test_release_unused_memory_trims_glibc_only_on_linux(monkeypatch):
    trims = []
    libc = SimpleNamespace(malloc_trim=lambda pad: trims.append(pad))
    monkeypatch.setattr(model_runtime.ctypes, "CDLL", lambda name: libc)
    monkeypatch.setattr(model_runtime.sys, "platform", "darwin")
    model_runtime.release_unused_memory()
    assert trims == []
    monkeypatch.setattr(model_runtime.sys, "platform", "linux")
    model_runtime.release_unused_memory()
    assert trims == [0]


def test_release_unused_memory_tolerates_a_libc_without_malloc_trim(monkeypatch):
    monkeypatch.setattr(model_runtime.sys, "platform", "linux")
    monkeypatch.setattr(model_runtime.ctypes, "CDLL", lambda name: SimpleNamespace())
    model_runtime.release_unused_memory()


class FakeProvider:
    enabled = True

    def __init__(self):
        self.ready = False
        self.load_requested = False
        self.preloads = 0
        self.unload_checks = []

    @property
    def available(self):
        return self.ready

    def preload(self):
        self.preloads += 1
        self.ready = True
        self.load_requested = False

    def request_load(self):
        if not self.ready:
            self.load_requested = True

    def unload_if_idle(self, idle_seconds):
        self.unload_checks.append(idle_seconds)
        if self.ready:
            self.ready = False
            return True
        return False


def worker_service(provider, idle_seconds):
    return SimpleNamespace(
        reranking_provider=provider, reranking_last_error=None,
        archiver=SimpleNamespace(settings=SimpleNamespace(
            semantic_retry_interval_seconds=60, search_rerank_idle_unload_seconds=idle_seconds)),
        _short_error=lambda message: message,
    )


async def run_worker(instance, rounds, between=None):
    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if between is not None:
            between(len(sleeps))
        if len(sleeps) >= rounds:
            raise asyncio.CancelledError
        await real_sleep(0)

    asyncio.sleep = fake_sleep
    try:
        with pytest.raises(asyncio.CancelledError):
            await ArchiveTaskService._run_reranking_worker(instance)
    finally:
        asyncio.sleep = real_sleep
    return sleeps


def test_default_worker_keeps_the_reranker_preloaded():
    provider = FakeProvider()
    sleeps = asyncio.run(run_worker(worker_service(provider, 0), 3))
    assert provider.ready and provider.preloads == 3
    assert provider.unload_checks == [] and sleeps == [60, 60, 60]


def test_idle_unload_worker_loads_only_on_request_then_unloads():
    provider = FakeProvider()
    instance = worker_service(provider, 600)

    def between(round_number):
        if round_number == 2:
            # A search found the model unloaded.
            provider.request_load()

    sleeps = asyncio.run(run_worker(instance, 4, between))
    # Rounds 1-2: nothing loaded at startup. Round 3: loaded on request. Round 4: idle unload.
    assert provider.preloads == 1
    assert provider.unload_checks == [600, 600, 600]
    assert not provider.ready and sleeps == [1, 1, 1, 1]


def test_idle_unload_worker_waits_the_retry_interval_after_a_failed_reload():
    provider = FakeProvider()
    provider.load_requested = True

    def fail():
        raise RuntimeError("model files missing")

    provider.preload = fail
    instance = worker_service(provider, 600)
    sleeps = asyncio.run(run_worker(instance, 2))
    assert sleeps == [60, 60]
    assert instance.reranking_last_error == "model files missing"


def test_search_requests_a_reload_when_the_reranker_is_unloaded():
    provider = FakeProvider()
    instance = SimpleNamespace(reranking_provider=provider)
    candidates = [dict(task=SimpleNamespace(id="a"), title="a", content="正文", lexical=0.0,
        terms=[], rank=0.5, evidence=None)]
    _rerank_candidates(instance, "如何配置防火墙", candidates, {})
    assert provider.load_requested and provider.preloads == 0
    assert candidates[0]["rank"] == 0.5
