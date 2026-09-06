from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session
from test_archive_api import make_database_url

from app.core.config import Settings
from app.core.db import run_migrations
from app.crud import ArchiveTaskRepository
from app.models import ArchiveTask
from app.search import context_excerpt, identifier_evidence_terms, lexical_evidence
from app.semantic import (
    SemanticDocumentPreparer,
    chunk_text,
    extract_readable_text,
    normalize_text,
    token_budget_chunks,
)
from app.service import ArchiveTaskService


def test_text_chunks_cover_short_tail_and_preserve_paragraphs() -> None:
    text = '甲' * 900 + '\n\n' + '乙' * 50
    chunks = chunk_text(text, min_chars=180, max_chars=900, overlap_chars=120)
    assert '乙' * 50 in chunks[-1]
    assert normalize_text('第一段\n\n第二段') == '第一段\n\n第二段'
    assert ''.join(chunks).count('甲') >= 900
    assert all(len(chunk) <= 900 for chunk in chunks)


def test_token_chunks_cover_every_character_and_reserve_title_budget() -> None:
    class CharacterTokenizer:
        def encode(self, value):
            return SimpleNamespace(ids=list(value) + [0, 1])
    text = '开头的内容。' * 80 + '最后的企鹅和数据库备份。'
    chunks, inputs = token_budget_chunks(text, '很长的标题' * 100, CharacterTokenizer(), 128)
    assert all(len(value) + 2 <= 128 for value in inputs)
    assert chunks[-1].endswith('最后的企鹅和数据库备份。')
    cursor = 0
    for chunk in chunks:
        start = text.find(chunk, max(0, cursor - 16))
        assert 0 <= start <= cursor
        cursor = start + len(chunk)
    assert cursor == len(text)


@pytest.mark.parametrize(('query', 'decoy', 'target'), [
    ('Go', 'Google 的新服务', 'Go 编程教程'),
    ('AI', 'daily email digest', 'AI 工具选择'),
    ('C++', 'C programming', 'C++ memory ownership'),
    ('.NET', 'internet networking', '.NET runtime'),
])
def test_short_identifiers_do_not_match_inside_words(query, decoy, target) -> None:
    assert lexical_evidence(decoy, [], '', '', query, True)[0] == 0
    assert lexical_evidence(target, [], '', '', query, True)[0] > 0


def test_excerpt_centers_actual_hit_in_late_paragraph() -> None:
    excerpt, paragraph = context_excerpt('简介。\n\n' + '铺垫' * 270 + '企鹅栖息地在南极。', ['企鹅栖息地'])
    assert paragraph == 1
    assert '企鹅栖息地' in excerpt
    assert excerpt.index('企鹅栖息地') < 80
    assert len(excerpt) <= 262


@pytest.fixture
def service(tmp_path: Path):
    settings = Settings(database_url=make_database_url(), archive_dir=tmp_path / 'archive',
        semantic_search_enabled=False)
    settings.archive_dir.mkdir()
    run_migrations(settings.database_url)
    repository = ArchiveTaskRepository(settings.database_url)
    return ArchiveTaskService(repository, SimpleNamespace(settings=settings), None, None,
        semantic_preparer=SemanticDocumentPreparer(180, 900, 120))


def save(service, task_id, title='存档', content='正文', url=None, read=False, source='manual'):
    with Session(service.repository.engine) as session:
        session.add(ArchiveTask(id=task_id, url=url or f'https://example.com/{task_id}',
            status='succeeded', output_file=f'{task_id}.html', entry_title=title,
            is_read=read, source_type=source))
        session.commit()
    path = service.archiver.settings.archive_dir / f'{task_id}.html'
    path.write_text('<html><body><article><p>' + content + '</p></article></body></html>')
    service._index_task_semantics(task_id)


def test_keyword_body_is_indexed_without_model_and_read_text_matches(service) -> None:
    save(service, 'tail', content='铺垫' * 900 + '末尾企鹅栖息地', read=True)
    page = service.search_tasks('企鹅栖息地', exact=True)
    assert [task.task_id for task in page.items] == ['tail']
    match = page.items[0].search_match
    assert match.kind == 'body'
    assert '企鹅栖息地' in match.excerpt
    assert match.highlights
    assert match.paragraph_highlights[0].start > 1000
    reading = service.get_search_text('tail')
    assert '企鹅栖息地' in reading.paragraphs[match.paragraph_index]
    assert service.search_tasks('企鹅栖息地', include_read=False).total == 0
    assert page.mode == 'keyword'
    assert page.coverage.ready == 1
    legacy = service.list_tasks(50, query='企鹅栖息地', include_read=True)
    assert legacy.items[0].task_id == 'tail'


def test_filters_apply_before_candidate_limit_and_literal_like_is_escaped(service) -> None:
    for i in range(5):
        save(service, str(i), title='热门内容', content='备份说明', source='rss')
    save(service, 'target', title='旧文章', content='独有 100%_reliable 的备份', source='manual')
    page = service.search_tasks('备份', source='manual', limit=1)
    assert page.total == 1
    assert page.items[0].task_id == 'target'
    assert service.search_tasks('100%_reliable', exact=True).total == 1
    assert service.search_tasks('not%_present', exact=True).total == 0


def test_semantic_candidates_apply_scope_before_the_article_limit(service) -> None:
    class Provider:
        model_name = 'scoped-semantic-test'
        available = True

        def embed(self, texts):
            return [[1.0] + [0.0] * 383 for _ in texts]

    save(service, 'a-outside', content='有关平静生活的资料', source='rss', read=True)
    save(service, 'z-target', content='有关平静生活的资料', source='manual')
    service.archiver.settings.semantic_search_enabled = True
    service.archiver.settings.search_candidate_limit = 1
    service.embedding_provider = Provider()
    for task_id in ['a-outside', 'z-target']:
        service._index_task_semantics(task_id)
    # Identical vectors would otherwise let the alphabetically earlier excluded
    # article consume the sole candidate slot. The question has no literal hit.
    for filters in [{'source': 'manual'}, {'include_read': False}]:
        page = service.search_tasks('怎样缓解精神压力', **filters)
        assert page.mode == 'hybrid'
        assert [task.task_id for task in page.items] == ['z-target']
        assert page.items[0].search_match.version_task_ids == ['z-target']


@pytest.mark.parametrize('query', ['NATS', 'NATS control-plane', 'C++ memory'])
def test_explicit_identifiers_do_not_accept_unrelated_semantic_results(service, monkeypatch, query) -> None:
    save(service, 'history-video', content='历史话剧以及一份 draft 草稿')
    with Session(service.repository.engine) as session:
        task = session.get(ArchiveTask, 'history-video')
        task.video_file = 'history.mp4'
        session.add(task)
        session.commit()
    service._semantic_enabled = lambda: True
    monkeypatch.setattr('app.search._semantic_candidates',
        lambda *_: {'history-video': [('历史话剧以及一份 draft 草稿', .9)]})
    assert service.search_tasks(query, content_type='video').total == 0


@pytest.mark.parametrize(('query', 'content'), [
    ('machine learning', '机器学习可以从数据中发现规律'),
    ('Machine Learning', '机器学习可以从数据中发现规律'),
    ('Public Speaking', '公开演讲需要练习表达与控制紧张情绪'),
])
def test_plain_english_phrase_can_still_find_chinese_semantic_content(service, monkeypatch, query, content) -> None:
    save(service, 'learning', content=content)
    service._semantic_enabled = lambda: True
    monkeypatch.setattr('app.search._semantic_candidates',
        lambda *_: {'learning': [(content, .9)]})
    assert service.search_tasks(query).items[0].task_id == 'learning'
    assert identifier_evidence_terms('who built AI') == []
    assert identifier_evidence_terms(query) == []
    assert identifier_evidence_terms('Paxos Raft') == []


def test_fully_scored_negative_semantic_candidates_return_no_results(service, monkeypatch) -> None:
    from test_search_reranking import NegativeReranker

    save(service, 'history', content='只有历史话剧的介绍')
    service._semantic_enabled = lambda: True
    service.reranking_provider = NegativeReranker()
    monkeypatch.setattr('app.search._semantic_candidates',
        lambda *_: {'history': [('只有历史话剧的介绍', .5)]})
    page = service.search_tasks('Paxos Raft')
    assert page.items == []
    assert page.total == 0 and not page.has_more


def test_model_upgrade_rebuilds_new_vectors_and_keeps_old_model_separate(service) -> None:
    class Provider:
        model_name = 'old-embedding-model'
        available = True
        last_error = None

        def embed(self, texts):
            return [[1.0] + [0.0] * 383 for _ in texts]

    save(service, 'upgrade', content='原有资料仍然能够搜索')
    service.archiver.settings.semantic_search_enabled = True
    provider = Provider()
    service.embedding_provider = provider
    old_version = service._semantic_text_version()
    service._index_task_semantics('upgrade')
    assert service.repository.semantic_index_record('upgrade', provider.model_name, old_version).status == 'indexed'
    provider.model_name = 'new-embedding-model'
    service.archiver.settings.semantic_text_version = 'new-text-version'
    assert service.repository.list_task_ids_requiring_semantic_index(provider.model_name, 384, 'new-text-version') == ['upgrade']
    assert service.search_tasks('原有资料', exact=True).total == 1
    service._index_task_semantics('upgrade')
    assert service.repository.list_task_ids_requiring_semantic_index(provider.model_name, 384, 'new-text-version') == []
    assert service.repository.semantic_index_record('upgrade', 'old-embedding-model', old_version).status == 'indexed'
    assert service.semantic_health().indexed_count == 1


@pytest.mark.parametrize('hidden_tag', ['script', 'noscript', 'style', 'template', 'svg', 'canvas'])
def test_readable_text_excludes_hidden_application_state_but_keeps_code(tmp_path, hidden_tag) -> None:
    path = tmp_path / 'saved.html'
    path.write_text('<html><body><article><h1>数据库设计教程</h1><p>'
        + '这是用户可以阅读的正文，解释数据库为什么需要索引。' * 10
        + '</p><pre>{"example": "public API"}</pre></article>'
        + f'<{hidden_tag} id="state">'
        + '[{"privateRecommendationPayload": "unrelated navigation"}]' * 30
        + f'</{hidden_tag}></body></html>')
    body = extract_readable_text(path)
    assert body is not None and '数据库为什么需要索引' in body
    assert 'privateRecommendationPayload' not in body
    assert 'public API' in body


def test_readable_upgrade_rebuilds_only_changed_bodies_and_disables_stale_vectors(service) -> None:
    from app.models import ArchiveSearchDocument

    class Provider:
        model_name = 'text-upgrade-test'
        available = True
        calls = 0

        def embed(self, texts):
            self.calls += 1
            return [[1.0] + [0.0] * 383 for _ in texts]

    save(service, 'unchanged', content='仍然有效的原始正文')
    save(service, 'changed', content='错误混入的推荐数据')
    service.archiver.settings.semantic_search_enabled = True
    provider = Provider()
    service.embedding_provider = provider
    for task_id in ['unchanged', 'changed']:
        service._index_task_semantics(task_id)
    assert provider.calls == 2
    with Session(service.repository.engine) as session:
        for task_id in ['unchanged', 'changed']:
            document = session.get(ArchiveSearchDocument, task_id)
            document.text_version = 'readable-v2'
            session.add(document)
        session.commit()
    (service.archiver.settings.archive_dir / 'changed.html').write_text(
        '<article><p>清理后的真实正文</p></article>')
    assert set(service.repository.list_task_ids_requiring_search_document()) == {'changed', 'unchanged'}
    for task_id in ['unchanged', 'changed']:
        service._index_task_semantics(task_id, lexical_only=True)
    assert service.repository.list_task_ids_requiring_search_document() == []
    version = service._semantic_text_version()
    assert service.repository.semantic_index_record('changed', provider.model_name, version).status == 'indexing'
    assert service.repository.semantic_index_record('unchanged', provider.model_name, version).status == 'indexed'
    for task_id in ['unchanged', 'changed']:
        service._index_task_semantics(task_id)
    assert provider.calls == 3
    assert service.repository.semantic_index_record('changed', provider.model_name, version).status == 'indexed'


def test_duplicate_urls_keep_matching_version_and_do_not_merge_query_parameters(service) -> None:
    save(service, 'match', content='企鹅栖息地', url='https://example.com/article?id=1')
    save(service, 'other-version', content='完全不同的文字', url='https://example.com/article?id=1')
    save(service, 'other-article', content='企鹅栖息地', url='https://example.com/article?id=2')
    page = service.search_tasks('企鹅栖息地', exact=True)
    assert page.total == 2
    matched = next(task for task in page.items if task.task_id == 'match')
    assert matched.search_match.version_count == 2
    assert set(matched.search_match.version_task_ids) == {'match', 'other-version'}


def test_model_failure_keeps_new_body_searchable(service) -> None:
    class FailingProvider:
        model_name = 'failure-test'
        available = True
        def embed(self, texts):
            raise RuntimeError('offline')
    save(service, 'failure', content='离线正文能够找到')
    service.archiver.settings.semantic_search_enabled = True
    service.embedding_provider = FailingProvider()
    with pytest.raises(RuntimeError, match='offline'):
        service._index_task_semantics('failure')
    page = service.search_tasks('离线正文')
    assert page.mode == 'keyword'
    assert page.items[0].task_id == 'failure'
    assert page.coverage.ready == 1


def test_quoted_phrase_is_required_even_for_semantic_candidates(service, monkeypatch) -> None:
    save(service, 'wrong', content='南极地区适合观察企鹅。')
    save(service, 'right', content='企鹅栖息地在南极。')
    service._semantic_enabled = lambda: True
    monkeypatch.setattr('app.search._semantic_candidates', lambda *_: {'wrong': ('南极地区适合观察企鹅。', .99)})
    page = service.search_tasks('"企鹅栖息地"')
    assert [task.task_id for task in page.items] == ['right']


def test_pending_legacy_text_remains_searchable_until_complete_backfill(service) -> None:
    from app.models import ArchiveSearchDocument
    save(service, 'legacy', content='旧索引中的企鹅')
    with Session(service.repository.engine) as session:
        document = session.get(ArchiveSearchDocument, 'legacy')
        document.text_version = 'legacy-v1'
        session.add(document)
        session.commit()
    page = service.search_tasks('企鹅', exact=True)
    assert page.total == 1
    assert page.coverage.pending == 1
    assert page.coverage.ready == 0
    assert service.get_search_text('legacy') is not None
    assert 'legacy' in service.repository.list_task_ids_requiring_search_document()
    service._index_task_semantics('legacy')
    assert service.search_tasks('企鹅', exact=True).coverage.ready == 1


def test_pending_and_unavailable_coverage_are_distinct(service) -> None:
    with Session(service.repository.engine) as session:
        session.add(ArchiveTask(id='pending', url='https://example.com/pending', status='succeeded', output_file='pending.html'))
        session.add(ArchiveTask(id='failed', url='https://example.com/failed', status='failed'))
        session.commit()
    coverage = service.search_tasks('').coverage
    assert (coverage.total, coverage.ready, coverage.pending, coverage.unavailable) == (2, 0, 1, 1)


def test_query_does_not_wait_indefinitely_for_background_model() -> None:
    import threading
    import time

    from app.semantic import LocalEmbeddingProvider
    provider = LocalEmbeddingProvider(Settings(semantic_query_lock_timeout_seconds=.01))
    acquired, release = threading.Event(), threading.Event()
    def hold():
        with provider._lock:
            acquired.set()
            release.wait(2)
    thread = threading.Thread(target=hold)
    thread.start()
    assert acquired.wait(1)
    start = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match='busy'):
            provider.embed_query('test busy model')
        assert time.monotonic() - start < .5
    finally:
        release.set()
        thread.join()


@pytest.mark.asyncio
async def test_text_worker_continues_while_model_is_busy(service) -> None:
    import asyncio
    import threading
    prepared = []
    release = threading.Event()
    model_started = threading.Event()
    def index(task_id, lexical_only=False):
        if lexical_only:
            prepared.append(task_id)
        else:
            model_started.set()
            release.wait(2)
    service._index_task_semantics = index
    service.archiver.settings.semantic_search_enabled = True
    workers = [asyncio.create_task(service._run_text_worker()), asyncio.create_task(service._run_semantic_worker())]
    try:
        await service.text_queue.put('first')
        await service.text_queue.put('second')
        await asyncio.wait_for(service.text_queue.join(), timeout=1)
        assert prepared == ['first', 'second']
        assert await asyncio.to_thread(model_started.wait, 1)
    finally:
        release.set()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_semantic_index_retries_without_restart(service) -> None:
    import asyncio
    class Provider:
        model_name = 'retry-test'
        last_error = None
        available = True
        failed = True
        def embed(self, texts):
            if self.failed:
                raise RuntimeError('temporary model failure')
            return [[1.0] + [0.0] * 383 for _ in texts]
    save(service, 'retry', content='暂时故障后的正文')
    service.archiver.settings.semantic_search_enabled = True
    service.archiver.settings.semantic_retry_interval_seconds = .02
    provider = Provider()
    service.embedding_provider = provider
    with pytest.raises(RuntimeError, match='temporary'):
        service._index_task_semantics('retry')
    provider.failed = False
    worker = asyncio.create_task(service._run_semantic_worker())
    try:
        async def wait_ready():
            while service.semantic_health().indexed_count != 1:
                await asyncio.sleep(.02)
        await asyncio.wait_for(wait_ready(), timeout=3)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


def test_upgrade_preserves_old_keyword_text_without_rebuilding_vectors(tmp_path) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    database_url = make_database_url()
    config = Config('alembic.ini')
    config.set_main_option('sqlalchemy.url', database_url)
    command.upgrade(config, '20260713_0008')
    repository = ArchiveTaskRepository(database_url)
    with Session(repository.engine) as session:
        session.add(ArchiveTask(id='old', url='https://example.com/old', status='succeeded', output_file='old.html'))
        session.commit()
        session.execute(text("""
            INSERT INTO reader_archive_semantic_chunks
            (id,task_id,chunk_index,content,content_hash,document_hash,model_name,embedding,created_at,updated_at)
            VALUES ('chunk0','old',0,'旧正文中的企鹅','old','old','old-model',CAST(:vector AS vector),CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
                   ('chunk1','old',1,'第二段文字','old','old','old-model',CAST(:vector AS vector),CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
        """), {'vector': '[' + ','.join(['0'] * 384) + ']'})
        session.commit()
    command.upgrade(config, 'head')
    document = repository.get_search_document('old')
    assert document.content == '旧正文中的企鹅\n\n第二段文字'
    assert document.text_version == 'legacy-v1'
    assert repository.list_task_ids_requiring_search_document() == ['old']
    with Session(repository.engine) as session:
        assert session.execute(text('SELECT count(*) FROM reader_archive_semantic_chunks')).scalar() == 2


def test_renaming_title_invalidates_embedding_hash(service) -> None:
    class Provider:
        model_name = 'title-change-test'
        available = True
        calls = 0
        def embed(self, texts):
            self.calls += 1
            return [[1.0] + [0.0] * 383 for _ in texts]
    save(service, 'rename', title='旧标题', content='正文完全相同')
    service.archiver.settings.semantic_search_enabled = True
    provider = Provider()
    service.embedding_provider = provider
    service._index_task_semantics('rename')
    service._index_task_semantics('rename')
    assert provider.calls == 1
    service.update_task_metadata('rename', custom_title_provided=True, custom_title='新标题')
    assert service.semantic_queue.qsize() == 1
    service._index_task_semantics('rename')
    assert provider.calls == 2
    assert service.search_tasks('新标题', exact=True).items[0].task_id == 'rename'
    assert service.search_tasks('旧标题', exact=True).items[0].task_id == 'rename'


def test_highlights_use_unicode_positions_and_identifier_boundaries() -> None:
    from app.search import highlight_ranges
    value = '😀daily email；AI 模型'
    highlights = highlight_ranges(value, ['ai'])
    assert len(highlights) == 1
    assert value[highlights[0].start:highlights[0].end] == 'AI'


def test_cold_model_does_not_load_on_search_request() -> None:
    from app.semantic import LocalEmbeddingProvider
    provider = LocalEmbeddingProvider(Settings())
    with pytest.raises(RuntimeError, match='preparing'):
        provider.embed_query('an uncached query')
    assert provider._model is None


@pytest.mark.asyncio
async def test_failed_model_preload_recovers_with_no_pending_documents(service) -> None:
    import asyncio
    class Provider:
        model_name = 'preload-retry-test'
        available = True
        last_error = None
        calls = 0
        loaded = False
        def preload(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError('temporary cold start failure')
            self.loaded = True
    provider = Provider()
    service.embedding_provider = provider
    service.archiver.settings.semantic_search_enabled = True
    service.archiver.settings.semantic_retry_interval_seconds = .02
    assert service.repository.list_task_ids_requiring_semantic_index(provider.model_name, 384, 'token-body-v2') == []
    worker = asyncio.create_task(service._run_semantic_worker())
    try:
        async def wait_loaded():
            while not provider.loaded:
                await asyncio.sleep(.01)
        await asyncio.wait_for(wait_loaded(), timeout=2)
        assert provider.calls >= 2
        assert service.semantic_last_error is None
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
