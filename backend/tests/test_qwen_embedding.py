from __future__ import annotations

import json
import math
import threading
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.qwen_embedding import (
    MODEL_NAME,
    MODEL_REVISION,
    QUERY_INSTRUCTION,
    QwenEmbeddingProvider,
    prepare_qwen_chunks,
)


class CharacterTokenizer:
    def __init__(self):
        self.calls = []

    def encode(self, value, **kwargs):
        return [ord(char) for char in value]

    def decode(self, values):
        return ''.join(chr(value) for value in values)

    def __call__(self, values, **kwargs):
        import torch
        self.calls.append((values, kwargs))
        size = max(map(len, values))
        ids = torch.tensor([[0]*(size-len(value))+self.encode(value) for value in values])
        return {'input_ids': ids, 'attention_mask': (ids != 0).long()}


class FakeModel:
    def __call__(self, input_ids, attention_mask):
        import torch
        axes = torch.arange(1, 1025, dtype=torch.float32)
        return SimpleNamespace(last_hidden_state=axes[None, None, :] + input_ids[:, :, None])


def provider():
    instance = QwenEmbeddingProvider(Settings(_env_file=None, semantic_search_enabled=True, semantic_model_name=MODEL_NAME,
        semantic_embedding_dimensions=384, semantic_query_lock_timeout_seconds=.01))
    instance._tokenizer = CharacterTokenizer()
    instance._model = FakeModel()
    return instance


def test_source_coverage_includes_chinese_short_tail_and_emoji():
    body = '这是长篇背景说明。'*130 + '最后是企鹅🐧育雏。'
    chunks = prepare_qwen_chunks(CharacterTokenizer(), '标题'*100, body)
    assert chunks[0].start == 0 and chunks[-1].end == len(body)
    assert all(chunk.content == body[chunk.start:chunk.end] for chunk in chunks)
    assert all(chunk.token_count <= 512 for chunk in chunks)
    assert all(right.start <= left.end for left, right in zip(chunks, chunks[1:], strict=False))
    assert '企鹅🐧育雏' in chunks[-1].content
    assert all(chunk.input_text.startswith(('标题'*100)[:64]+'\n\n') for chunk in chunks)


def test_natural_sentences_are_preserved_when_they_fit():
    body = 'First complete sentence. Second complete sentence. '*20
    chunks = prepare_qwen_chunks(CharacterTokenizer(), 'Title', body, budget=120)
    assert all(chunk.content.endswith('sentence. ') for chunk in chunks)
    assert all(right.start > left.start for left, right in zip(chunks, chunks[1:], strict=False))


def test_overlong_sentence_splits_without_dropping_tail():
    body = '字'*1600+'尾'
    chunks = prepare_qwen_chunks(CharacterTokenizer(), '', body)
    assert ''.join(chunk.content for chunk in chunks) == body
    assert all(chunk.token_count <= 512 for chunk in chunks)
    assert prepare_qwen_chunks(CharacterTokenizer(), 'title', '') == []


def test_query_instruction_and_cache_are_separate_from_document_inputs():
    item = provider()
    first = item.embed_query('缓存请求收费吗')
    assert item._tokenizer.calls[0][0] == [f'Instruct: {QUERY_INSTRUCTION}\nQuery:缓存请求收费吗']
    assert item.embed_query('缓存请求收费吗') == first
    assert len(item._tokenizer.calls) == 1
    item.embed(['正文'])
    assert item._tokenizer.calls[1][0] == ['正文']


def test_last_token_pooling_projection_and_normalization():
    item = provider()
    vectors = item.embed(['a', 'longa'])
    assert len(vectors) == 2 and len(vectors[0]) == 384
    assert vectors[0] == pytest.approx(vectors[1])
    assert math.sqrt(sum(value*value for value in vectors[0])) == pytest.approx(1)
    assert vectors[0][-1]/vectors[0][0] == pytest.approx((384+ord('a'))/(1+ord('a')))
    assert item._tokenizer.calls[0][1]['truncation'] is False


def test_index_batches_are_bounded_even_when_caller_requests_many():
    item = provider()
    assert len(item.embed(['body']*11)) == 11
    assert [len(call[0]) for call in item._tokenizer.calls] == [4, 4, 3]


def test_oversized_inputs_are_rejected_instead_of_silently_truncated():
    item = provider()
    with pytest.raises(ValueError, match='exceeds 512'):
        item.embed(['x'*513])
    assert item.available


def test_busy_query_lock_falls_back_without_waiting_for_background_work():
    item = provider()
    acquired, release = threading.Event(), threading.Event()
    def hold():
        with item._lock:
            acquired.set()
            release.wait(2)
    thread = threading.Thread(target=hold)
    thread.start()
    assert acquired.wait(1)
    try:
        with pytest.raises(RuntimeError, match='busy'):
            item.embed_query('query')
    finally:
        release.set()
        thread.join()


def test_cold_query_does_not_start_loading():
    item = QwenEmbeddingProvider(Settings(_env_file=None, semantic_search_enabled=True, semantic_model_name=MODEL_NAME))
    with pytest.raises(RuntimeError, match='preparing'):
        item.embed_query('query')
    assert item._model is None


def test_preload_failure_retries_without_pending_articles(monkeypatch):
    item = provider()
    calls = []
    def load():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('temporary failure')
        return item._model
    monkeypatch.setattr(item, '_load_model', load)
    with pytest.raises(RuntimeError, match='temporary'):
        item.preload()
    assert not item.available
    item._failed_at -= item.settings.semantic_retry_interval_seconds+1
    item.preload()
    assert item.available and item.last_error is None


def test_local_model_resolution_never_downloads(tmp_path):
    item = QwenEmbeddingProvider(Settings(_env_file=None, semantic_search_enabled=True, semantic_model_name=MODEL_NAME,
        semantic_model_dir=tmp_path))
    with pytest.raises(RuntimeError, match='missing'):
        item._resolve_model_path()
    (tmp_path/'config.json').write_text('{}')
    assert item._resolve_model_path() == tmp_path


@pytest.mark.parametrize('field', ['model_name', 'revision'])
def test_standalone_model_identity_mismatch_rejected_before_runtime_import(tmp_path, monkeypatch, field):
    import builtins

    manifest = {'model_name': MODEL_NAME, 'revision': MODEL_REVISION}
    manifest[field] = 'different'
    (tmp_path/'config.json').write_text('{}')
    (tmp_path/'reader-model.json').write_text(json.dumps(manifest))
    item = QwenEmbeddingProvider(Settings(_env_file=None, semantic_search_enabled=True, semantic_model_name=MODEL_NAME,
        semantic_model_dir=tmp_path))
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name not in {'torch', 'transformers'}, 'Identity must be checked before loading the runtime.'
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded_import)
    with pytest.raises(ValueError, match='identity'):
        item.preload()
    assert item._model is None


def test_matching_standalone_model_identity_resolves(tmp_path):
    (tmp_path/'config.json').write_text('{}')
    (tmp_path/'reader-model.json').write_text(json.dumps({
        'model_name': MODEL_NAME, 'revision': MODEL_REVISION}))
    item = QwenEmbeddingProvider(Settings(_env_file=None, semantic_search_enabled=True, semantic_model_name=MODEL_NAME,
        semantic_model_dir=tmp_path))
    assert item._resolve_model_path() == tmp_path
