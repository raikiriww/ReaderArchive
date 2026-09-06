"""Bounded Chinese/Latin BM25 recall over an already scoped document snapshot.

This supplements literal matching. Scores are relative ranks, not relevance
probabilities; exact terms and quoted phrases must still be checked by callers.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass

import jieba
from rank_bm25 import BM25L


@dataclass(frozen=True)
class LexicalDocument:
    task_id: str
    title: str
    content: str
    tags: tuple[str, ...] = ()
    url: str = ""
    revision: str = ""


@dataclass(frozen=True)
class LexicalMatch:
    score: float
    terms: tuple[str, ...]
    coverage: float


@dataclass(frozen=True)
class _Index:
    task_ids: tuple[str, ...]
    term_sets: tuple[frozenset[str], ...]
    model: BM25L | None


# Stop function words, not technical nouns (including one-character nouns like 键).
# These are tokenizer input cleanup, not a list of preferred topics or answers.
_STOP_WORDS = frozenset("""
的 了 着 是 在 和 与 等 我 你 他 她 它 这 那 吗 呢 地 得 让 给 来 去 从 到 对 将 中
上 下 为 后 前 会 能 不 很 再 只 还 更 就 也 都 但 把 被 及 又 于 呀 啊 哦
怎么 如何 为什么 其实 谁 是谁 是否 什么 可以 进行 通过 这个 那个 时候 以后 之前 一个
我们 你们 他们 她们 它们 就是 因为 所以 以及 或者 而且 但是 需要 应该 能够 哪些 这样 那样
a an the of in to is are be been being was were it its this that these those i you your we our
ours they their them as and or but if then than with without from for how what which why who when
where can could should would do does did have has had
don't doesn't didn't isn't aren't wasn't weren't can't couldn't won't wouldn't shouldn't
it's that's there's i'm you're we're they're i've you've we've they've
""".split())
_TOKEN_GROUPS = re.compile(r"[\u3400-\u9fff]+|[.+#]?[A-Za-z0-9][A-Za-z0-9_.+#/'’-]*")
_CHINESE = re.compile(r"[\u3400-\u9fff]+")
_TOKENIZER_VERSION = "jieba-precise-identifiers-v2"
_segmenter = jieba.Tokenizer()
_segmenter_lock = threading.RLock()
_cache_lock = threading.RLock()
_cache: OrderedDict[str, _Index] = OrderedDict()
_CACHE_SIZE = 2


def tokenize(value: str) -> list[str]:
    """Segment each Chinese run while keeping C++, .NET, Go and names atomic."""
    result: list[str] = []
    for match in _TOKEN_GROUPS.finditer(value):
        group = match.group()
        if _CHINESE.fullmatch(group):
            with _segmenter_lock:
                words = list(_segmenter.cut(group, HMM=False))
        else:
            # A sentence-ending period is punctuation; a leading .NET dot is not.
            words = [group.rstrip(".").replace("’", "'")]
        result.extend(word.casefold() for word in words
            if word.strip() and word.casefold() not in _STOP_WORDS)
    return result


def _fingerprint(documents: Sequence[LexicalDocument]) -> str:
    digest = hashlib.sha256(_TOKENIZER_VERSION.encode())
    for document in documents:
        # Include actual contents as well as caller revision: a stale revision must
        # not reuse stale text, and title/tag edits may leave a body hash unchanged.
        for value in (document.task_id, document.revision, document.title,
                      document.content, document.url, *document.tags):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        digest.update(b"\0document-end\0")
    return digest.hexdigest()


def _build_index(documents: Sequence[LexicalDocument]) -> _Index:
    task_ids: list[str] = []
    corpus: list[list[str]] = []
    for document in documents:
        title = tokenize(document.title)
        tags = tokenize(" ".join(document.tags))
        tokens = title * 3 + tags * 2 + tokenize(document.content) + tokenize(document.url)
        if not tokens:
            continue
        task_ids.append(document.task_id)
        corpus.append(tokens)
    # BM25L has positive IDF even in tiny filtered corpora. Okapi's negative
    # small-corpus IDF would otherwise make a genuine one-document match negative.
    return _Index(tuple(task_ids), tuple(frozenset(tokens) for tokens in corpus),
                  BM25L(corpus) if corpus else None)


def _get_index(documents: Sequence[LexicalDocument]) -> _Index:
    ordered = sorted(documents, key=lambda document: document.task_id)
    if len({document.task_id for document in ordered}) != len(ordered):
        raise ValueError("BM25 input must contain unique task_id values.")
    key = _fingerprint(ordered)
    # Publish only complete immutable snapshots. Building is serialized so two
    # initial requests cannot duplicate a large corpus/tokenizer initialization.
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached
        index = _build_index(ordered)
        _cache[key] = index
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
        return index


def search_bm25(query: str, documents: Sequence[LexicalDocument], *,
                limit: int = 120) -> dict[str, LexicalMatch]:
    """Return at most ``limit`` scoped candidates, ordered by descending BM25.

    A multi-term query needs at least two meaningful terms and at least 40% of
    its unique terms. Merely mentioning AI in an otherwise unrelated document
    does not qualify for a longer request. Single-term lookups remain supported.
    This is only a recall gate; callers should label these candidates as possible
    matches and apply their normal phrase constraints and ranking checks.
    """
    if limit <= 0 or not documents:
        return {}
    query_tokens = tuple(dict.fromkeys(tokenize(query)))
    if not query_tokens:
        return {}
    index = _get_index(documents)
    if index.model is None:
        return {}
    required_count = 1 if len(query_tokens) == 1 else max(2, math.ceil(len(query_tokens) * .4))
    scores = index.model.get_scores(query_tokens)
    matches: list[tuple[str, LexicalMatch]] = []
    for task_id, terms, raw_score in zip(index.task_ids, index.term_sets, scores, strict=True):
        matched = tuple(token for token in query_tokens if token in terms)
        score = float(raw_score)
        if len(matched) < required_count or score <= 0 or not math.isfinite(score):
            continue
        matches.append((task_id, LexicalMatch(score=score, terms=matched,
                                            coverage=len(matched) / len(query_tokens))))
    matches.sort(key=lambda item: (-item[1].score, item[0]))
    return dict(matches[:limit])
