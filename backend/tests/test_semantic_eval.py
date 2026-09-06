from pathlib import Path

import pytest

from app.core.config import Settings
from scripts.semantic_eval import (
    ARTICLES,
    QUERIES,
    EvalHttpClient,
    EvalQuery,
    assert_isolated_seed_target,
    build_summary,
    evaluate_case,
    reset_database,
)


def result(task_id, excerpt=""):
    return {"task_id": task_id, "search_match": {"excerpt": excerpt}}


@pytest.mark.parametrize("response", [[result("good")], {"items": [result("good")], "total": 1, "has_more": False}])
def test_accepts_current_page_and_legacy_array(response, monkeypatch):
    client = EvalHttpClient("http://localhost")
    requests = []
    monkeypatch.setattr(client, "request_json", lambda method, path: requests.append(path) or response)
    assert client.search("Go") == [result("good")]
    assert requests[0].startswith("/api/v1/archive-search?")


@pytest.mark.parametrize("response", [{"total": 0}, {"items": {}}, [None], [{"title": "missing id"}]])
def test_invalid_search_response_fails_loudly(response, monkeypatch):
    client = EvalHttpClient("http://localhost")
    monkeypatch.setattr(client, "request_json", lambda *args: response)
    with pytest.raises(RuntimeError, match="invalid result items"):
        client.search("query")


def test_correct_article_second_is_failure():
    case = evaluate_case(EvalQuery("question", ("good",), "rewrite"),
                         [result("decoy"), result("good")], 10)
    assert not case["passed"]
    assert case["reciprocal_rank_at_10"] == 0.5
    assert case["precision_at_5"] == 0.5
    assert case["ndcg_at_10"] < 1


def test_correct_first_does_not_hide_irrelevant_results_or_duplicates():
    for extra in ["decoy", "good"]:
        case = evaluate_case(EvalQuery("question", ("good",), "rewrite"),
                             [result("good"), result(extra)], 10)
        assert case["primary_first"]
        assert not case["passed"]
        assert case["precision_at_5"] == .5


def test_one_good_result_need_not_fill_five_slots():
    case = evaluate_case(EvalQuery("question", ("good",), "rewrite"), [result("good")], 10)
    assert case["passed"]
    assert case["precision_at_5"] == 1
    assert case["ndcg_at_10"] == 1


def test_missing_tail_excerpt_fails_even_with_correct_first():
    case = evaluate_case(EvalQuery("tail", ("good",), "tail", "末段证据"),
                         [result("good", "文章开头")], 10)
    assert not case["passed"]
    assert case["excerpt_supported"] is False


def test_summary_separates_false_positives_quality_and_latency():
    cases = [evaluate_case(EvalQuery("tail", ("good",), "tail", "证据"),
                           [result("good", "证据")], 10),
             evaluate_case(EvalQuery("absent", (), "unrelated"), [result("decoy")], 30)]
    summary = build_summary(cases, [10, 30])
    assert summary["passed_cases"] == 1
    assert summary["unrelated_false_positive_rate"] == 1
    assert summary["evidence_support_rate"] == 1
    assert summary["p95_duration_ms"] == 30
    assert summary["by_kind"]["unrelated"] == {"passed": 0, "count": 1}


def isolated_settings(**kwargs):
    return Settings(_env_file=None, database_url=kwargs.get("database_url", "postgresql+psycopg://reader:reader@eval-db:5432/reader_semantic_eval"),
                    archive_dir=kwargs.get("archive_dir", Path("/app/eval-data/archive")))


@pytest.mark.parametrize("kwargs", [
    {"database_url": "postgresql+psycopg://reader:reader@db:5432/reader"},
    {"database_url": "postgresql+psycopg://reader:reader@production:5432/reader_semantic_eval"},
    {"archive_dir": Path("/app/data/archive")},
])
def test_seed_rejects_nonisolated_targets_before_connecting(kwargs, monkeypatch):
    monkeypatch.setenv("READER_EVAL_ALLOW_RESET", "isolated-semantic-eval")
    monkeypatch.setattr("scripts.semantic_eval.get_engine", lambda *_: pytest.fail("must not connect"))
    with pytest.raises(RuntimeError, match="Refusing destructive seed"):
        reset_database(isolated_settings(**kwargs))


def test_seed_requires_explicit_reset_marker(monkeypatch):
    monkeypatch.delenv("READER_EVAL_ALLOW_RESET", raising=False)
    with pytest.raises(RuntimeError, match="Refusing destructive seed"):
        assert_isolated_seed_target(isolated_settings())


def test_guard_accepts_only_dedicated_config(monkeypatch):
    monkeypatch.setenv("READER_EVAL_ALLOW_RESET", "isolated-semantic-eval")
    assert_isolated_seed_target(isolated_settings())


def test_fixture_ids_and_judgments_are_consistent():
    ids = [article.task_id for article in ARTICLES]
    assert len(ids) == len(set(ids))
    for query in QUERIES:
        assert set(query.expected) <= set(ids)
    assert sum(query.kind == "unrelated" for query in QUERIES) >= 4
    assert {query.query for query in QUERIES} >= {"Go", "C++", "帝企鹅育雏"}


def test_seed_refuses_existing_nonfixture_rows_before_truncation(monkeypatch):
    monkeypatch.setenv("READER_EVAL_ALLOW_RESET", "isolated-semantic-eval")
    statements = []

    class FakeSession:
        def __init__(self, engine):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement):
            statements.append(str(statement))
            return self

        def scalars(self):
            return ["user-archive-that-must-survive"]

    monkeypatch.setattr("scripts.semantic_eval.get_engine", lambda *_: object())
    monkeypatch.setattr("scripts.semantic_eval.Session", FakeSession)
    with pytest.raises(RuntimeError, match="non-evaluation archives"):
        reset_database(isolated_settings())
    assert statements == ["SELECT id FROM reader_archive_tasks"]


def test_topic_query_accepts_either_document_that_answers_it_first():
    query = EvalQuery("topic", ("a", "b"), "rewrite")
    assert evaluate_case(query, [result("b"), result("a")], 10)["passed"]
    target = EvalQuery("specific title", ("a", "b"), "keyword")
    assert not evaluate_case(target, [result("b"), result("a")], 10)["passed"]
