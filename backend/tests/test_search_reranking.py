from __future__ import annotations

import threading
from collections import OrderedDict
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.search import _rerank_candidates
from app.search_passages import SourcePassage, evidence_windows, source_window


class FakeReranker:
    available = True

    def __init__(self, *, failure=None, failure_round=2, max_passages=400):
        self.failure = failure
        self.failure_round = failure_round
        self.max_passages = max_passages
        self.calls = []

    def score(self, query, passages):
        self.calls.append(list(passages))
        if len(passages) > self.max_passages:
            raise ValueError("pair budget exceeded")
        if len(self.calls) == self.failure_round and self.failure == 'raise':
            raise RuntimeError("CPU model busy during evidence selection")
        # The same source always receives the same model score across rounds.
        scores = [2.0 if '乙' in passage or '第二篇' in passage else
            1.0 if '甲' in passage or '第一篇' in passage else
            sum(ord(char) for char in passage) / 100000 for passage in passages]
        if len(self.calls) == self.failure_round and self.failure == 'short':
            return scores[:-1]
        return scores


def service(provider):
    return SimpleNamespace(
        reranking_provider=provider, reranking_last_error=None,
        archiver=SimpleNamespace(settings=SimpleNamespace(
            search_passages_per_article=3, search_rerank_evidence_articles=5, search_candidate_limit=200)),
        _short_error=lambda message: message,
    )


def candidate(task_id, content, rank=0.01):
    return dict(task=SimpleNamespace(id=task_id), document=None, title=task_id,
        content=content, lexical=2.0, kind='body', terms=['目标'], matched_title=task_id,
        rank=rank, evidence=None)


@pytest.mark.parametrize('failure', ['raise', 'short'])
@pytest.mark.parametrize('failure_round', [1, 2, 3])
def test_evidence_failure_restores_every_original_rank_and_quote(failure, failure_round):
    provider = FakeReranker(failure=failure, failure_round=failure_round)
    instance = service(provider)
    candidates = [candidate('a', '甲文章介绍。目标答案在这里。', 0.12),
        candidate('b', '乙文章介绍。目标答案在别处。', 0.34)]
    original = deepcopy(candidates)
    _rerank_candidates(instance, '目标是什么', candidates, {})
    assert provider.calls and len(provider.calls) == failure_round
    assert instance.reranking_last_error
    assert candidates == original


def test_scored_quotes_remain_exact_substrings_at_declared_source_offsets():
    provider = FakeReranker()
    instance = service(provider)
    candidates = [candidate('a', '甲文章介绍。\n\n目标答案在这里。后续解释。'),
        candidate('b', '乙文章介绍。目标答案在别处。')]
    _rerank_candidates(instance, '目标是什么', candidates, {})
    assert instance.reranking_last_error is None
    for item in candidates:
        quote = item['evidence']
        assert quote is not None
        assert item['content'][quote.start:quote.end] == quote.text
    assert candidates[1]['rank'] > candidates[0]['rank']


def test_reranking_and_evidence_calls_respect_provider_pair_budget():
    provider = FakeReranker(max_passages=2)
    instance = service(provider)
    candidates = [candidate(str(index), f'文章{index}。目标内容。后续解释。') for index in range(6)]
    _rerank_candidates(instance, '目标', candidates, {})
    assert provider.calls
    assert all(len(passages) <= provider.max_passages for passages in provider.calls)
    assert instance.reranking_last_error is None


def test_long_source_window_does_not_drop_the_matched_fragment_tail():
    fragment = '目标' * 400 + '最后答案。'
    content = '前' * 100 + fragment + '后' * 100
    window = source_window(content, fragment, width=650)
    assert window is not None
    assert window.text == content[window.start:window.end]
    assert '最后答案。' in window.text


def test_evidence_windows_preserve_source_unicode_and_repeated_sentences():
    content = '重复一句。\n\n📚这里解释原因。重复一句。最后一句。'
    start = content.index('📚')
    passage = SourcePassage(content[start:], start, len(content))
    for quote in evidence_windows(passage, width=15):
        assert quote.text == content[quote.start:quote.end]
        assert quote.start >= start


def test_limited_cpu_budget_selects_same_articles_regardless_of_database_row_order():
    candidates = [candidate(str(index), f'文章{index}。目标内容。', rank=index / 10) for index in range(6)]
    first, second = FakeReranker(max_passages=2), FakeReranker(max_passages=2)
    _rerank_candidates(service(first), '目标', deepcopy(candidates), {})
    _rerank_candidates(service(second), '目标', list(reversed(deepcopy(candidates))), {})
    assert first.calls[0] == second.calls[0]


def test_exact_metadata_navigation_stays_above_inferred_content_without_a_body():
    provider = FakeReranker()
    metadata = candidate('metadata', '', rank=0.47)
    metadata.update(lexical=4.5, kind='tag')
    inferred = candidate('inferred', '文章介绍。目标内容。', rank=0.02)
    candidates = [metadata, inferred]
    _rerank_candidates(service(provider), '目标', candidates, {})
    assert metadata['rank'] > inferred['rank']


def test_display_evidence_fits_one_reader_paragraph_for_correct_highlight_location():
    content = '这里只是文章介绍。\n\n📚真正的目标答案在第二段。后续说明。'
    passage = SourcePassage(content, 0, len(content))
    quotes = evidence_windows(passage, width=260)
    assert any('目标答案' in quote.text for quote in quotes)
    for quote in quotes:
        assert '\n\n' not in quote.text
        assert quote.text == content[quote.start:quote.end]
        paragraph_index = content[:quote.start].count('\n\n')
        paragraphs = content.split('\n\n')
        paragraph_start = sum(len(value) + 2 for value in paragraphs[:paragraph_index])
        assert paragraph_start <= quote.start < quote.end <= paragraph_start + len(paragraphs[paragraph_index])


def cached_service(provider):
    instance = service(provider)
    instance.search_ranking_cache = OrderedDict()
    instance.search_ranking_cache_lock = threading.Lock()
    return instance


class NegativeReranker(FakeReranker):
    def score(self, query, passages):
        self.calls.append(list(passages))
        if self.failure == 'raise' and len(self.calls) == 2:
            raise RuntimeError('complete coverage scoring failed')
        return [1.0 if 'positive-tail' in passage else -9.0 for passage in passages]


def inferred_candidate(task_id, content):
    item = candidate(task_id, content)
    item.update(lexical=0, terms=[])
    return item


def test_uniformly_negative_inferred_results_are_rejected_and_cached():
    provider = NegativeReranker()
    instance = cached_service(provider)
    original = [inferred_candidate('a', '无关历史视频。'), inferred_candidate('b', '其他无关内容。')]
    candidates = deepcopy(original)
    _rerank_candidates(instance, '寻找特定主题', candidates, {})
    assert all(item['rank'] == -1 for item in candidates)
    assert len(provider.calls) == 2
    provider.available = False
    replay = deepcopy(original)
    _rerank_candidates(instance, '寻找特定主题', replay, {})
    assert all(item['rank'] == -1 for item in replay)


def test_negative_first_window_cannot_discard_positive_alternate_window():
    provider = NegativeReranker()
    item = inferred_candidate('a', 'negative-head.' + '填充' * 500 + 'positive-tail.')
    _rerank_candidates(service(provider), '寻找特定主题', [item],
        {'a': [('negative-head.', .9), ('positive-tail.', .8)]})
    assert item['rank'] >= 0
    assert any('positive-tail' in passage for passage in provider.calls[1])


def test_negative_first_slice_cannot_discard_positive_later_slice():
    class Sliced(NegativeReranker):
        def split_passage(self, query, text):
            parts, cursor = [], 0
            while cursor < len(text):
                part = text[cursor:cursor + 100]
                parts.append(part)
                if cursor + len(part) == len(text):
                    break
                cursor += len(part) - min(16, len(part) // 5)
            return parts

    provider = Sliced()
    body = '填充' * 120 + 'positive-tail.'
    item = inferred_candidate('a', body)
    _rerank_candidates(service(provider), '寻找特定主题', [item], {'a': [(body, .9)]})
    assert item['rank'] >= 0
    assert any('positive-tail' in passage for passage in provider.calls[0])


def test_incomplete_budget_does_not_reject_unscored_alternate_windows():
    provider = NegativeReranker(max_passages=1)
    item = inferred_candidate('a', 'negative-head.' + '填充' * 500 + 'negative-tail.')
    _rerank_candidates(service(provider), '寻找特定主题', [item],
        {'a': [('negative-head.', .9), ('negative-tail.', .8)]})
    assert item['rank'] >= 0


def test_token_slice_budget_cannot_be_mistaken_for_complete_coverage():
    class Sliced(NegativeReranker):
        def split_passage(self, query, text):
            return [text[:100], text[84:]] if len(text) > 100 else [text]

    provider = Sliced(max_passages=1)
    body = '填充' * 80 + 'positive-tail.'
    item = inferred_candidate('a', body)
    _rerank_candidates(service(provider), '寻找特定主题', [item], {'a': [(body, .9)]})
    assert all(len(passages) <= 1 for passages in provider.calls)
    assert item['rank'] >= 0


def test_complete_negative_check_failure_restores_original_candidates():
    provider = NegativeReranker(failure='raise')
    instance = service(provider)
    item = inferred_candidate('a', '无关的历史资料。')
    original = deepcopy(item)
    _rerank_candidates(instance, '寻找特定主题', [item], {})
    assert item == original
    assert instance.reranking_last_error


def test_mixed_literal_candidates_never_enter_negative_rejection():
    provider = NegativeReranker()
    items = [inferred_candidate('a', '无关内容。'), candidate('b', '目标内容。')]
    _rerank_candidates(service(provider), '寻找特定主题', items, {})
    assert all(item['rank'] >= 0 for item in items)


def test_cached_complete_order_survives_busy_model_and_database_row_reordering(monkeypatch):
    provider = FakeReranker()
    instance = cached_service(provider)
    original = [candidate('a', '第一篇。目标内容。'), candidate('b', '第二篇。目标内容。')]
    first = deepcopy(original)
    _rerank_candidates(instance, '目标', first, {})
    expected = {item['task'].id: (item['rank'], item['evidence']) for item in first}
    def cannot_score(query, passages):
        raise AssertionError('cached pagination must not score again')
    monkeypatch.setattr(provider, 'score', cannot_score)
    provider.available = False
    second = list(reversed(deepcopy(original)))
    _rerank_candidates(instance, '目标', second, {})
    assert {item['task'].id: (item['rank'], item['evidence']) for item in second} == expected
    assert instance.reranking_last_error is None


@pytest.mark.parametrize('change', ['content', 'scope', 'model'])
def test_order_cache_does_not_reuse_changed_source_scope_or_model(change):
    provider = FakeReranker()
    instance = cached_service(provider)
    original = [candidate('a', '第一篇。目标内容。'), candidate('b', '第二篇。目标内容。')]
    _rerank_candidates(instance, '目标', deepcopy(original), {})
    calls = len(provider.calls)
    updated = deepcopy(original)
    if change == 'content':
        updated[0]['content'] = '修改后。不同的目标内容。'
    elif change == 'scope':
        updated.pop()
    else:
        provider.model_name = 'a-different-model'
    _rerank_candidates(instance, '目标', updated, {})
    assert len(provider.calls) > calls


def test_order_cache_expires_and_has_bounded_capacity(monkeypatch):
    provider = FakeReranker()
    instance = cached_service(provider)
    now = [100.0]
    monkeypatch.setattr('app.search.time.monotonic', lambda: now[0])
    original = [candidate('a', '文章介绍。目标内容。')]
    _rerank_candidates(instance, '目标', deepcopy(original), {})
    calls = len(provider.calls)
    now[0] += 61
    _rerank_candidates(instance, '目标', deepcopy(original), {})
    assert len(provider.calls) > calls
    for index in range(35):
        _rerank_candidates(instance, f'问题{index}', deepcopy(original), {})
    assert len(instance.search_ranking_cache) <= 32


def test_explicit_technical_keywords_keep_literal_results_without_model_wait():
    provider = FakeReranker()
    item = candidate('technical', '共识算法包括 Paxos 和 Raft。', rank=.31)
    item.update(lexical=3.0, terms=['Paxos', 'Raft'])
    _rerank_candidates(service(provider), 'Paxos Raft', [item], {})
    assert provider.calls == []
    assert item['rank'] == .31


def test_first_article_window_scores_all_token_slices_including_its_tail():
    class Splitter(FakeReranker):
        def split_passage(self, query, text):
            result=[]
            cursor=0
            while cursor<len(text):
                part=text[cursor:cursor+5]
                result.append(part)
                if cursor+len(part)==len(text):
                    break
                cursor += len(part)-min(16,len(part)//5)
            return result
    provider=Splitter()
    target=candidate('a','甲甲甲甲甲甲甲甲乙乙乙乙',rank=.01)
    target.update(lexical=0,terms=[])
    instance=service(provider)
    _rerank_candidates(instance,'要找什么',[target],{'a':[(target['content'],.8)]})
    assert any('乙乙' in part for part in provider.calls[0])
    assert instance.reranking_last_error is None
