"""Archive search: independent readable text, scoped retrieval and source evidence.

Scores are internal ranks only. They are deliberately not confidence percentages.
"""
from __future__ import annotations

import hashlib
import re
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, TypedDict

from sqlalchemy import case, func, or_, text
from sqlalchemy import select as sa_select
from sqlmodel import col, select

from app.archive_formats import FILE_ARCHIVE_SUFFIXES
from app.lexical_search import LexicalDocument, search_bm25
from app.models import (
    ArchiveSearchDocument,
    ArchiveSearchRead,
    ArchiveTag,
    ArchiveTask,
    ArchiveTaskSearchMatch,
    ArchiveTaskTag,
    SearchCoverage,
    SearchHighlight,
)
from app.search_passages import SourcePassage, evidence_windows, source_window

if TYPE_CHECKING:
    from datetime import datetime

    from app.service import ArchiveTaskService


class SearchCandidate(TypedDict):
    task: ArchiveTask
    document: SimpleNamespace | None
    title: str
    content: str
    lexical: float
    kind: str
    terms: list[str]
    matched_title: str
    rank: float
    evidence: SourcePassage | None


def query_terms(query: str) -> tuple[list[str], list[str]]:
    """Quoted text stays contiguous; Latin identifiers retain symbols like C++."""
    quoted = re.findall(r'["“]([^"”]+)["”]', query)
    remainder = re.sub(r'["“][^"”]+["”]', ' ', query)
    terms = quoted + re.findall(r"[\u3400-\u9fff]+|[.+#]?[^\W_][\w.+#:/@%-]*", remainder)
    return list(dict.fromkeys(term.casefold() for term in terms if term)), quoted


def term_pattern(term: str) -> str:
    escaped = re.escape(term)
    if re.fullmatch(r"[\x00-\x7f]+", term) and not any(c.isspace() for c in term):
        return r"(?<![a-z0-9_])" + escaped + r"(?![a-z0-9_+])"
    return escaped


def contains_term(value: str, term: str) -> bool:
    return bool(re.search(term_pattern(term), value, re.IGNORECASE))


def identifier_evidence_terms(query: str) -> list[str]:
    """Explicit names/code identifiers need a real mention, not topical proximity."""
    if not re.fullmatch(r'[A-Za-z0-9.+#_/-]+(?:\s+[A-Za-z0-9.+#_/-]+){0,2}', query):
        return []
    words = query.split()
    if words[0].casefold() in {'who', 'what', 'why', 'how', 'when', 'where', 'which'}:
        return []
    code_or_acronym = any(
        any(symbol in word for symbol in '.+#_/-')
        or (len(word) >= 2 and word.isupper())
        or bool(re.search(r'[a-z][A-Z]', word)) for word in words)
    # Title case alone is not an identifier signal: "Machine Learning" and
    # "Public Speaking" still need to find translated concepts without an
    # English literal mention. Proper names with the same shape remain semantic.
    return [word.casefold() for word in words] if code_or_acronym else []


def highlight_ranges(value: str, terms: list[str]) -> list[SearchHighlight]:
    spans: list[tuple[int, int]] = []
    for term in sorted(terms, key=len, reverse=True):
        for match in re.finditer(term_pattern(term), value, re.IGNORECASE):
            if not any(start < match.end() and end > match.start() for start, end in spans):
                spans.append((match.start(), match.end()))
    # Unicode codepoint offsets. Clients must slice Array.from(text), not UTF-16 units.
    return [SearchHighlight(start=start, end=end) for start, end in sorted(spans)]


def context_excerpt(content: str, terms: list[str], width: int = 260) -> tuple[str, int]:
    paragraphs = content.split("\n\n")
    best_index = max(range(len(paragraphs)), key=lambda i: sum(
        len(term) for term in terms if contains_term(paragraphs[i], term)))
    paragraph = paragraphs[best_index]
    positions = [match.start() for term in terms
        for match in re.finditer(term_pattern(term), paragraph, re.IGNORECASE)]
    start = max(0, min(positions, default=0) - 40)
    excerpt = paragraph[start:start + width]
    return ("…" if start else "") + excerpt + ("…" if start + width < len(paragraph) else ""), best_index


def lexical_evidence(title: str, tags: list[str], url: str, content: str,
                     query: str, exact: bool) -> tuple[float, str, list[str]]:
    terms, quoted = query_terms(query)
    if not terms:
        return 0, "body", []
    fields = [title.casefold(), " ".join(tags).casefold(), url.casefold(), content.casefold()]
    combined = "\n".join(fields)
    if any(not contains_term(combined, phrase.casefold()) for phrase in quoted):
        return 0, "body", terms
    phrase = query.strip('"“”').casefold()
    if phrase == fields[0]:
        return 6, "title", terms
    if contains_term(fields[0], phrase):
        return 5, "title", terms
    if contains_term(fields[1], phrase):
        return 4.5, "tag", terms
    if contains_term(fields[2], phrase):
        return 4, "url", terms
    if contains_term(fields[3], phrase):
        return 3.5, "body", terms
    if all(contains_term(combined, term) for term in terms):
        if all(contains_term(fields[0], term) for term in terms):
            return 5, "title", terms
        if all(contains_term(fields[1], term) for term in terms):
            return 4.5, "tag", terms
        return 3, "body" if any(contains_term(fields[3], term) for term in terms) else "title", terms
    if exact or quoted:
        return 0, "body", terms
    # Conservative Chinese fallback; no fabricated cross-script bigrams or 45% matches.
    expanded = [piece for term in terms for piece in (
        [term[i:i + 2] for i in range(len(term) - 1)]
        if re.fullmatch(r'[\u3400-\u9fff]{3,}', term) else [term])]
    found = [term for term in expanded if contains_term(combined, term)]
    if len(found) >= 3 and len(found) / len(expanded) >= 0.8:
        best_field = max(range(4), key=lambda i: sum(contains_term(fields[i], term) for term in found))
        return 1 + len(found) / len(expanded), ["title", "tag", "url", "body"][best_field], found
    return 0, "body", terms


def _semantic_candidates(service: ArchiveTaskService, query: str, task_ids: list[str]) -> dict[str, list[tuple[str, float]]]:
    if not task_ids or not service._semantic_enabled():
        return {}
    provider = service.embedding_provider
    assert provider is not None
    embeddings = [list(provider.embed_query(query))] if hasattr(provider, "embed_query") else provider.embed([query])
    if len(embeddings) != 1:
        raise RuntimeError("Query embedding was not generated.")
    service._validate_embedding_dimensions(embeddings[0])
    repository = service.repository
    with repository._session() as session:
        # Rank within each article before bounding articles; keep alternate evidence.
        rows = session.execute(text("""
            WITH scored AS (
                SELECT chunk.task_id, chunk.content, chunk.chunk_index,
                       1 - (chunk.embedding <=> CAST(:embedding AS vector)) AS score,
                       row_number() OVER (PARTITION BY chunk.task_id ORDER BY
                           chunk.embedding <=> CAST(:embedding AS vector), chunk.chunk_index) AS passage_rank
                FROM reader_archive_semantic_chunks chunk
                JOIN reader_archive_semantic_indexes idx ON idx.task_id = chunk.task_id
                     AND idx.model_name = chunk.model_name AND idx.document_hash = chunk.document_hash
                WHERE chunk.model_name = :model AND idx.text_version = :version
                    AND idx.status = 'indexed' AND chunk.task_id = ANY(:task_ids)
            ), articles AS (
                SELECT task_id, score FROM scored WHERE passage_rank = 1 AND score >= :minimum
                ORDER BY score DESC, task_id LIMIT :limit
            )
            SELECT scored.task_id, scored.content, scored.score FROM scored
            JOIN articles USING (task_id) WHERE passage_rank <= :passages
            ORDER BY articles.score DESC, scored.task_id, passage_rank
        """), dict(embedding=repository._vector_literal(embeddings[0]),
            model=provider.model_name, version=service._semantic_text_version(), task_ids=task_ids,
            minimum=service.archiver.settings.semantic_min_score,
            limit=service.archiver.settings.search_candidate_limit,
            passages=service.archiver.settings.search_passages_per_article)).all()
    result: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        result.setdefault(str(row.task_id), []).append((str(row.content), float(row.score)))
    return result


def _bounded_passage_pairs(pairs: list[tuple[SearchCandidate, SourcePassage]],
                           budget: int) -> list[tuple[SearchCandidate, SourcePassage]]:
    groups: dict[str, list[tuple[SearchCandidate, SourcePassage]]] = {}
    for pair in pairs:
        groups.setdefault(pair[0]['task'].id, []).append(pair)
    result = []
    for index in range(max((len(group) for group in groups.values()), default=0)):
        for group in groups.values():
            if index < len(group):
                result.append(group[index])
                if len(result) >= budget:
                    return result
    return result


def _fit_passage_pairs(provider, query: str, pairs: list[tuple[SearchCandidate, SourcePassage]]):
    if not hasattr(provider, 'split_passage'):
        return pairs
    result = []
    for item, window in pairs:
        cursor = 0
        for part in provider.split_passage(query, window.text):
            if window.text[cursor:cursor + len(part)] != part:
                raise ValueError('Ranking window does not match its source.')
            result.append((item, SourcePassage(part, window.start + cursor,
                window.start + cursor + len(part))))
            cursor += len(part) - min(16, len(part) // 5)
    return result


def _rerank_candidates(service: ArchiveTaskService, query: str,
                       candidates: list[SearchCandidate],
                       semantic: dict[str, list[tuple[str, float]]]) -> None:
    provider = getattr(service, 'reranking_provider', None)
    if provider is None or not candidates:
        return
    if any(item['lexical'] >= 5 for item in candidates) or query_terms(query)[1]:
        return
    # Short explicit technical keywords already have strong literal evidence;
    # avoid a costly semantic pass for navigation-style searches.
    keyword_query = bool(re.fullmatch(
        r'[A-Za-z0-9.+#_/-]+(?:\s+[A-Za-z0-9.+#_/-]+){0,2}', query))
    if keyword_query and not re.match(r'(?i)^(who|what|why|how|when|where|which)\b', query) and any(
            item['lexical'] >= 3 for item in candidates):
        return
    cache = getattr(service, 'search_ranking_cache', None)
    cache_lock = getattr(service, 'search_ranking_cache_lock', None)
    signature = hashlib.sha256(repr((query, getattr(provider, 'model_name', ''),
        getattr(provider, 'revision', ''), getattr(provider, 'quantization', 'none'),
        getattr(provider, 'effective_quantization', None), getattr(provider, 'quantization_engine', None),
        getattr(provider, 'max_length', 0))).encode())
    for item in sorted(candidates, key=lambda value: value['task'].id):
        signature.update(repr((item['task'].id, item['title'], item['content'], item['rank'],
            item['lexical'], item['terms'])).encode())
    cache_key = signature.hexdigest()
    if cache is not None and cache_lock is not None:
        with cache_lock:
            cached = cache.get(cache_key)
            if cached is not None and time.monotonic() - cached[0] < 60:
                for item in candidates:
                    item['rank'], item['evidence'] = cached[1][item['task'].id]
                cache.move_to_end(cache_key)
                return
    if not provider.available:
        return
    original = [(item, item['rank'], item.get('evidence')) for item in candidates]
    settings = service.archiver.settings
    pairs: list[tuple[SearchCandidate, SourcePassage]] = []
    for item in sorted(candidates, key=lambda value: (-value['rank'], value['task'].id)):
        fragments = [value[0] for value in semantic.get(item['task'].id, [])]
        if item['lexical'] and item['content']:
            excerpt, _ = context_excerpt(item['content'], item['terms'])
            # Broad keyword hits can occur in an unrelated section of a weekly
            # digest. The semantic window leads; literal evidence is an extra
            # option, not a replacement for that window.
            fragments.append(excerpt.strip('…'))
        if not fragments:
            fragments = [item['content'][:400] or item['title']]
        seen: set[tuple[int, int]] = set()
        for fragment in fragments[:settings.search_passages_per_article]:
            window = source_window(item['content'], fragment)
            if window is None:
                continue
            key = (window.start, window.end)
            if key not in seen:
                seen.add(key)
                pairs.append((item, window))
    if not pairs:
        return
    budget = getattr(provider, 'max_passages', settings.search_candidate_limit * 6)
    try:
        primary_windows = _bounded_passage_pairs(pairs, len({item['task'].id for item, _ in pairs}))
        complete_pairs = _fit_passage_pairs(provider, query, pairs)
        pairs = _bounded_passage_pairs(complete_pairs, budget)
        # First compare one window per article, then spend additional work on
        # alternative passages in the leading articles. Long pages must not
        # consume the entire online CPU budget before other articles are seen.
        first_pairs = _bounded_passage_pairs(_fit_passage_pairs(provider, query, primary_windows), budget)
        scores = provider.score(query, [window.text for _, window in first_pairs])
        best: dict[str, tuple[float, SourcePassage]] = {}
        for (item, window), score in zip(first_pairs, scores, strict=True):
            task_id = item['task'].id
            if task_id not in best or score > best[task_id][0]:
                best[task_id] = (score, window)
        rejected_ids: set[str] = set()
        # Only an entirely inferred, uniformly very weak result set can enter
        # rejection. Check every selected window/slice before dropping anything;
        # a CPU budget cap or missing article must never masquerade as coverage.
        rejection_floor = -8.0
        candidate_ids = {item['task'].id for item in candidates}
        if (all(item['lexical'] == 0 for item in candidates)
                and candidate_ids == set(best)
                and all(value[0] < rejection_floor for value in best.values())
                and len(complete_pairs) <= budget
                and candidate_ids == {item['task'].id for item, _ in complete_pairs}):
            complete_scores = provider.score(query, [window.text for _, window in complete_pairs])
            for (item, window), score in zip(complete_pairs, complete_scores, strict=True):
                task_id = item['task'].id
                if score > best[task_id][0]:
                    best[task_id] = (score, window)
            rejected_ids = {task_id for task_id, value in best.items() if value[0] < rejection_floor}
        ordered = sorted(best, key=lambda task_id: (-best[task_id][0], task_id))
        ranks = {task_id: index for index, task_id in enumerate(ordered, 1)}
        # Keep exact title/tag/URL navigation above inferred relevance.
        for item in candidates:
            task_id = item['task'].id
            item['rank'] = (1 if item['lexical'] >= 4 else 0) + (
                1 / (1 + ranks[task_id]) if task_id in best else 0)
            if task_id in rejected_ids:
                item['rank'] = -1
        # Evidence selection is separate: compare full source sentence windows.
        leading = sorted((item for item in candidates if item['rank'] >= 0),
            key=lambda value: value['rank'], reverse=True)[
            :settings.search_rerank_evidence_articles]
        leading_ids = {item['task'].id for item in leading if item['lexical'] < 4}
        alternate_pairs = [(item, window) for item, window in pairs if item['task'].id in leading_ids]
        if alternate_pairs:
            alternate_scores = provider.score(query, [window.text for _, window in alternate_pairs])
            for (item, window), score in zip(alternate_pairs, alternate_scores, strict=True):
                task_id = item['task'].id
                if score > best[task_id][0]:
                    best[task_id] = (score, window)
        evidence_pairs: list[tuple[SearchCandidate, SourcePassage]] = []
        for item in leading:
            if item['task'].id in best and item['lexical'] < 4:
                window = best[item['task'].id][1]
                evidence_pairs.extend((item, quote) for quote in evidence_windows(window))
        if evidence_pairs:
            evidence_pairs = _bounded_passage_pairs(
                _fit_passage_pairs(provider, query, evidence_pairs), budget)
            quote_scores = provider.score(query, [quote.text for _, quote in evidence_pairs])
            quote_best: dict[str, float] = {}
            for (item, quote), score in zip(evidence_pairs, quote_scores, strict=True):
                task_id = item['task'].id
                if task_id not in quote_best or score > quote_best[task_id]:
                    quote_best[task_id] = score
                    item['evidence'] = quote
        service.reranking_last_error = None
        if cache is not None and cache_lock is not None:
            with cache_lock:
                cache[cache_key] = (time.monotonic(), {item['task'].id:
                    (item['rank'], item['evidence']) for item in candidates})
                while len(cache) > 32:
                    cache.popitem(last=False)
    except Exception as exc:
        # Existing retrieval remains usable during model preparation/failure/busy periods.
        for item, rank, evidence in original:
            item['rank'], item['evidence'] = rank, evidence
        service.reranking_last_error = service._short_error(str(exc))


def search_archive(service: ArchiveTaskService, *, query: str, limit: int, offset: int,
                   include_read: bool, tags: list[str] | None, content_type: str,
                   source: str | None, date_from: datetime | None,
                   exact: bool, sort: str, statuses: list[str] | None = None,
                   group_duplicates: bool = True) -> ArchiveSearchRead:
    repository = service.repository
    query = " ".join(query.split())
    scope = select(ArchiveTask.id)
    if not include_read:
        scope = scope.where(ArchiveTask.is_read == False)  # noqa: E712
    if statuses:
        scope = scope.where(col(ArchiveTask.status).in_(statuses))
    if source:
        scope = scope.where(ArchiveTask.source_type == source)
    if date_from:
        scope = scope.where(ArchiveTask.created_at >= date_from)
    if tags:
        tagged = select(ArchiveTaskTag.task_id).join(ArchiveTag, ArchiveTag.id == ArchiveTaskTag.tag_id).where(
            func.lower(ArchiveTag.name).in_([tag.casefold() for tag in tags]))
        scope = scope.where(col(ArchiveTask.id).in_(tagged))
    is_file_archive = or_(*(col(ArchiveTask.output_file).ilike('%' + suffix)
        for suffix in FILE_ARCHIVE_SUFFIXES))
    if content_type == "video":
        scope = scope.where(ArchiveTask.video_file != None)  # noqa: E711
    elif content_type == "file":
        scope = scope.where(is_file_archive)
    elif content_type == "web":
        scope = scope.where(ArchiveTask.video_file == None,  # noqa: E711
            or_(ArchiveTask.output_file == None, ~is_file_archive))  # noqa: E711

    with repository._session() as session:
        scoped_tasks = session.execute(sa_select(col(ArchiveTask.id), col(ArchiveTask.url), col(ArchiveTask.status), col(ArchiveTask.output_file), col(ArchiveTask.page_error)).where(
            col(ArchiveTask.id).in_(scope)).order_by(col(ArchiveTask.created_at).desc(), ArchiveTask.id)).all()
        task_ids = [row[0] for row in scoped_tasks]
        versions: dict[str, list[str]] = {}
        for task_id, url, _, _, _ in scoped_tasks:
            versions.setdefault(url, []).append(task_id)
        coverage_rows = session.exec(select(ArchiveSearchDocument.task_id,
            ArchiveSearchDocument.status, ArchiveSearchDocument.text_version).where(
            col(ArchiveSearchDocument.task_id).in_(scope))).all()
    prepared = {task_id: (status, version) for task_id, status, version in coverage_rows}
    ready = sum(status == "ready" and version == "readable-v3" for status, version in prepared.values())
    unavailable = sum(status == "unavailable" for status, _ in prepared.values())
    unavailable += sum(task_id not in prepared and (status == "failed" or
        (status == "succeeded" and (not output_file or bool(page_error))))
        for task_id, _, status, output_file, page_error in scoped_tasks)
    coverage = SearchCoverage(total=len(task_ids), ready=ready,
        unavailable=unavailable, pending=len(task_ids) - ready - unavailable)
    if not query or not task_ids:
        return ArchiveSearchRead(items=[], total=0, limit=limit, offset=offset,
            has_more=False, coverage=coverage)

    semantic: dict[str, list[tuple[str, float]]] = {}
    mode = "keyword"
    identifier_query = bool(re.fullmatch(r"[.+#]?[A-Za-z][A-Za-z0-9.+#_-]*", query)) and (
        len(query) <= 3 or any(symbol in query for symbol in ".+#_-"))
    if not exact and not identifier_query and service._semantic_enabled():
        try:
            semantic = _semantic_candidates(service, query, task_ids)
            mode = "hybrid"
            service.semantic_last_error = None
        except Exception as exc:
            service.semantic_last_error = service._short_error(str(exc))
    bm25 = {}
    if not exact and not identifier_query:
        with repository._session() as session:
            documents = session.exec(select(ArchiveTask, ArchiveSearchDocument).outerjoin(
                ArchiveSearchDocument, ArchiveSearchDocument.task_id == ArchiveTask.id).where(
                col(ArchiveTask.id).in_(scope))).all()
            scope_tags = session.exec(select(ArchiveTaskTag.task_id, ArchiveTag.name).join(
                ArchiveTag, ArchiveTag.id == ArchiveTaskTag.tag_id).where(
                col(ArchiveTaskTag.task_id).in_(task_ids))).all()
            tag_map: dict[str, list[str]] = {}
            for task_id, name in scope_tags:
                tag_map.setdefault(task_id, []).append(name)
            bm25 = search_bm25(query, [LexicalDocument(task_id=task.id,
                title=task.custom_title or task.entry_title or task.video_title or '',
                content=doc.content if doc and doc.status == 'ready' else '',
                url=task.url, tags=tuple(tag_map.get(task.id, []))) for task, doc in documents],
                limit=service.archiver.settings.search_candidate_limit)
    terms, _ = query_terms(query)
    # Retrieval considers each script separately; broad bigrams only add candidates,
    # while lexical_evidence enforces complete words/phrases or conservative coverage.
    retrieval_terms = terms if exact else terms + [term[i:i + 2] for term in terms
        if re.fullmatch(r'[\u3400-\u9fff]{3,}', term) for i in range(len(term) - 1)]
    tag_text = select(func.string_agg(ArchiveTag.name, ' ')).join(
        ArchiveTaskTag, ArchiveTag.id == ArchiveTaskTag.tag_id).where(
        ArchiveTaskTag.task_id == ArchiveTask.id).scalar_subquery()
    haystack = func.concat_ws(' ', ArchiveTask.custom_title, ArchiveTask.entry_title,
        ArchiveTask.video_title, ArchiveTask.url, tag_text)
    predicates = [or_(haystack.ilike('%' + repository._escape_like(term) + '%', escape='\\'),
        col(ArchiveSearchDocument.content).ilike('%' + repository._escape_like(term) + '%', escape='\\'))
        for term in retrieval_terms]
    if bm25:
        predicates.append(col(ArchiveTask.id).in_(list(bm25)))
    if semantic:
        predicates.append(col(ArchiveTask.id).in_(list(semantic)))
    if not predicates:
        return ArchiveSearchRead(items=[], total=0, limit=limit, offset=offset,
            has_more=False, mode=mode, coverage=coverage)
    with repository._session() as session:
        body_for_ranking = ArchiveSearchDocument.content
        if re.fullmatch(r'[\u3400-\u9fff]+', query):
            title_value = func.coalesce(ArchiveTask.custom_title, ArchiveTask.entry_title,
                ArchiveTask.video_title, ArchiveTask.url)
            body_for_ranking = case((title_value.ilike('%' + query + '%'), ''),
                else_=ArchiveSearchDocument.content)
        raw_rows = session.exec(select(ArchiveTask, ArchiveSearchDocument.file_name,
            ArchiveSearchDocument.status, body_for_ranking).outerjoin(
            ArchiveSearchDocument, ArchiveSearchDocument.task_id == ArchiveTask.id).where(
            col(ArchiveTask.id).in_(scope), or_(*predicates))).all()
        rows = [(task, SimpleNamespace(file_name=file_name, status=status, content=content)
            if file_name is not None else None) for task, file_name, status, content in raw_rows]
        candidate_ids = [task.id for task, _ in rows]
        tag_rows = session.exec(select(ArchiveTaskTag.task_id, ArchiveTag.name).join(
            ArchiveTag, ArchiveTag.id == ArchiveTaskTag.tag_id).where(
            col(ArchiveTaskTag.task_id).in_(candidate_ids))).all() if candidate_ids else []
        task_tags: dict[str, list[str]] = {}
        for task_id, name in tag_rows:
            task_tags.setdefault(task_id, []).append(name)
        candidates: list[SearchCandidate] = []
        for task, document in rows:
            title = task.custom_title or task.entry_title or task.video_title or repository._title_from_url(task.url)
            content = document.content if document and document.status == 'ready' else ''
            titles = list(dict.fromkeys(value for value in [title, task.entry_title, task.video_title] if value))
            required_identifiers = identifier_evidence_terms(query)
            candidate_text = "\n".join([*titles, " ".join(task_tags.get(task.id, [])), task.url, content])
            if required_identifiers and not any(contains_term(candidate_text, term) for term in required_identifiers):
                continue
            _, quoted = query_terms(query)
            if any(not contains_term("\n".join([*titles, " ".join(task_tags.get(task.id, [])), task.url, content]), phrase) for phrase in quoted):
                continue
            title_matches = [(lexical_evidence(alias, task_tags.get(task.id, []), task.url, content, query, exact), alias) for alias in titles]
            (score, kind, hit_terms), matched_title = max(title_matches, key=lambda item: item[0][0])
            if not score and task.id in bm25:
                score, kind, hit_terms = 1.0, 'body', list(bm25[task.id].terms)
            if not score and task.id not in semantic:
                continue
            candidates.append(SearchCandidate(task=task, document=document, title=title, rank=0, evidence=None,
                content=content, lexical=score, kind=kind, terms=hit_terms, matched_title=matched_title))
        lexical_order = sorted((item for item in candidates if item['lexical']),
            key=lambda item: (-item['lexical'], -getattr(bm25.get(item['task'].id), 'score', 0), item['task'].id))
        lexical_ranks = {item['task'].id: rank for rank, item in enumerate(lexical_order, 1)}
        semantic_ranks = {task_id: rank for rank, task_id in enumerate(semantic, 1)}
        for item in candidates:
            task_id = item['task'].id
            # Strong literal evidence stays ahead; then fuse rankings, never raw cosine + boosts.
            item['rank'] = (0.1 * item['lexical'] if item['lexical'] >= 3 else 0) + (
                1 / (60 + lexical_ranks[task_id]) if task_id in lexical_ranks else 0) + (
                1 / (60 + semantic_ranks[task_id]) if task_id in semantic_ranks else 0)
        if not exact and not identifier_query:
            _rerank_candidates(service, query, candidates, semantic)
        candidates = [item for item in candidates if item['rank'] >= 0]
        if sort == 'oldest':
            candidates.sort(key=lambda item: (item['task'].created_at, item['task'].id))
        elif sort == 'newest':
            candidates.sort(key=lambda item: (item['task'].created_at, item['task'].id), reverse=True)
        else:
            candidates.sort(key=lambda item: (item['rank'], item['task'].created_at, item['task'].id), reverse=True)
        if group_duplicates:
            grouped: dict[str, SearchCandidate] = {}
            for candidate in candidates:
                grouped.setdefault(candidate['task'].url, candidate)
            candidates = list(grouped.values())
        results = []
        for item in candidates[offset:offset + limit]:
            task, document, kind = item['task'], item['document'], item['kind']
            paragraph_index = None
            paragraph_highlights = []
            if item['evidence'] is not None or (not item['lexical'] and task.id in semantic):
                kind = 'semantic'
                chunk = item['evidence'].text if item['evidence'] is not None else semantic[task.id][0][0]
                position = item['evidence'].start if item['evidence'] is not None else item['content'].find(chunk)
                if position >= 0:
                    paragraph_index = item['content'][:position].count('\n\n')
                    paragraph_start = item['content'].rfind('\n\n', 0, position) + 2
                    if paragraph_index == 0:
                        paragraph_start = 0
                    paragraph = item['content'].split('\n\n')[paragraph_index]
                    start = position - paragraph_start
                    paragraph_highlights = [SearchHighlight(start=start,
                        end=min(len(paragraph), start + len(chunk)))]
                excerpt = chunk if item['evidence'] is not None else chunk[:260] + ('…' if len(chunk) > 260 else '')
            elif kind == 'body' and item['content']:
                excerpt, paragraph_index = context_excerpt(item['content'], item['terms'])
                paragraph_highlights = highlight_ranges(item['content'].split('\n\n')[paragraph_index], item['terms'])
            elif kind == 'tag':
                excerpt = ' · '.join(task_tags.get(task.id, []))
            elif kind == 'url':
                excerpt = task.url
            else:
                excerpt = item['matched_title']
            match = ArchiveTaskSearchMatch(excerpt=excerpt, score=item['rank'], kind=kind,
                strength="strong" if item["lexical"] >= 3 else "possible",
                highlights=highlight_ranges(excerpt, item['terms']) if kind != 'semantic' else [],
                file_name=document.file_name if document and document.status == 'ready' else None,
                paragraph_index=paragraph_index, paragraph_highlights=paragraph_highlights,
                location_text=f"第 {paragraph_index + 1} 段" if paragraph_index is not None else None,
                version_count=len(versions[task.url]), version_task_ids=versions[task.url])
            result = repository._to_task(session, task).model_copy(update={'search_match': match})
            results.append(service._with_existing_result_files(result))
    return ArchiveSearchRead(items=results, total=len(candidates), limit=limit, offset=offset,
        has_more=offset + len(results) < len(candidates), mode=mode, coverage=coverage,
        total_is_exact=mode == 'keyword')
