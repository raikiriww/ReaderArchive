from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.lexical_search import LexicalDocument, search_bm25, tokenize


def test_chinese_query_recovers_reordered_content_without_full_phrase() -> None:
    documents = [
        LexicalDocument('cache', '请求缓存设计', '缓存能复用已经计算过的结果。稳定的请求前缀有助于提高命中率。'),
        LexicalDocument('ai-news', 'AI 行业新闻', '提高工作效率的 AI 工具每天都在更新。'),
        LexicalDocument('weather', '周末天气', '周末适合去公园散步。'),
    ]
    matches = search_bm25('怎么提高缓存命中率', documents)
    assert list(matches) == ['cache']
    assert {'缓存', '命中率'} <= set(matches['cache'].terms)
    assert matches['cache'].score > 0


def test_single_ai_mention_cannot_recall_a_long_request() -> None:
    documents = [
        LexicalDocument('review', '开发协作', '代码审查意见反复交给 AI 修改。审查人员负责确认实现是否满足需求。'),
        LexicalDocument('ai-only', '科技新闻', 'AI 改变社会，带来很多机会。'),
        LexicalDocument('irrelevant', '厨房整理', '收纳盒分类以后取用非常方便。'),
    ]
    matches = search_bm25('把代码审查意见反复交给 AI 修改，其实是谁在完成实现', documents)
    assert 'review' in matches
    assert 'ai-only' not in matches
    assert 'irrelevant' not in matches
    assert matches['review'].coverage >= .4


@pytest.mark.parametrize(('query', 'target', 'decoy'), [
    ('Go', 'Go 编程语言入门', 'Google 搜索技巧'),
    ('AI', 'AI 工具', 'OpenAI daily email'),
    ('C++', 'C++ 内存管理', 'C 编程语言'),
    ('.NET', '.NET 运行时', 'internet networking'),
])
def test_latin_identifiers_are_not_substring_matches(query, target, decoy) -> None:
    matches = search_bm25(query, [LexicalDocument('target', target, ''), LexicalDocument('decoy', decoy, '')])
    assert list(matches) == ['target']
    assert query.casefold() in matches['target'].terms


def test_mixed_script_tokenization_does_not_create_cross_script_bigrams() -> None:
    tokens = tokenize('AI提高缓存命中率，使用C++与.NET；Go不是Google。')
    assert {'ai', '缓存', '命中率', 'c++', '.net', 'go', 'google'} <= set(tokens)
    assert not any(token in tokens for token in ['i提', '用c', 'ai提高'])


def test_english_contractions_do_not_create_spurious_identifier_terms() -> None:
    assert tokenize("Don't cache secrets; we’re testing.") == ['cache', 'secrets', 'testing']
    matches = search_bm25("Don't cache secrets", [
        LexicalDocument('target', 'Cache secrets carefully', ''),
        LexicalDocument('decoy', 'Don writes about T cells', ''),
    ])
    assert list(matches) == ['target']


def test_empty_and_unknown_queries_do_not_return_arbitrary_documents() -> None:
    documents = [LexicalDocument('empty', '', ''), LexicalDocument('stop', '的 了 the', '')]
    assert search_bm25('缓存', documents) == {}
    assert search_bm25('的 the 是 什么', documents) == {}
    assert search_bm25('', documents) == {}
    assert search_bm25('缓存', []) == {}
    assert search_bm25('quasar', [LexicalDocument('cache', '缓存命中率', '')]) == {}


def test_one_document_scope_has_a_positive_score_and_cannot_leak_other_scopes() -> None:
    first = LexicalDocument('first', '备份恢复指南', '保存多个备份能够恢复文件。')
    second = LexicalDocument('second', '备份存储', '检查备份。')
    assert list(search_bm25('备份', [first])) == ['first']
    assert search_bm25('备份', [first])['first'].score > 0
    assert list(search_bm25('备份', [second])) == ['second']


def test_cache_invalidates_on_body_metadata_revision_and_deleted_documents() -> None:
    original = LexicalDocument('edit', '旧标题', '缓存指南', tags=('标签',), revision='v1')
    assert 'edit' in search_bm25('缓存', [original])
    changed_body = replace(original, content='企鹅育雏指南')
    assert search_bm25('缓存', [changed_body]) == {}
    assert 'edit' in search_bm25('企鹅', [changed_body])
    changed_title = replace(changed_body, title='容器网络', tags=('配置',), revision='v2')
    assert 'edit' in search_bm25('容器', [changed_title])
    assert search_bm25('标签', [changed_title]) == {}
    assert search_bm25('企鹅', []) == {}


def test_candidates_are_bounded_and_ties_stable_across_input_order() -> None:
    documents = [LexicalDocument(str(i), '缓存命中率', '缓存命中率') for i in range(20)]
    first = search_bm25('缓存', documents, limit=3)
    second = search_bm25('缓存', list(reversed(documents)), limit=3)
    assert len(first) == 3
    assert first == second
    assert list(first) == sorted(first)
    assert search_bm25('缓存', documents, limit=0) == {}


def test_concurrent_queries_keep_scope_and_snapshot_contents_separate() -> None:
    scopes = [
        [LexicalDocument('cache', '缓存命中率', '缓存设计')],
        [LexicalDocument('backup', '备份策略', '恢复文件')],
    ]
    requests = [('缓存', scopes[0]), ('备份', scopes[1])] * 10
    with ThreadPoolExecutor(max_workers=6) as pool:
        outputs = list(pool.map(lambda item: search_bm25(item[0], item[1]), requests))
    assert all(set(output) == ({'cache'} if index % 2 == 0 else {'backup'})
               for index, output in enumerate(outputs))


def test_duplicate_task_ids_are_rejected_instead_of_silently_overwriting() -> None:
    with pytest.raises(ValueError, match='unique task_id'):
        search_bm25('缓存', [LexicalDocument('same', '缓存', ''), LexicalDocument('same', '备份', '')])
