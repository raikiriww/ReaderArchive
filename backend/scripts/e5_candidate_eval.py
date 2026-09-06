"""Offline-only E5-small experiment; never registers or changes the production default."""
from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from sqlalchemy import make_url, text
from sqlmodel import Session
from tokenizers import Tokenizer

from app.archiver import BrowserOpener, SingleFileArchiver, YtDlpDownloader
from app.core.config import Settings
from app.core.db import get_engine, run_migrations
from app.crud import ArchiveTaskRepository
from app.search import search_archive
from app.semantic import LocalEmbeddingProvider, SemanticDocumentPreparer, token_budget_chunks
from app.service import ArchiveTaskService
from scripts.semantic_eval import (
    ARTICLES,
    QUERIES,
    build_summary,
    evaluate_case,
    render_article_html,
    render_markdown,
)

MODEL = "eval/intfloat-multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
ROOT = Path(__file__).resolve().parents[2]


class E5EvaluationProvider(LocalEmbeddingProvider):
    def __init__(self, settings: Settings, model_path: Path):
        super().__init__(settings)
        self.model_path = model_path

    def _load_model(self):
        if self._model is None:
            self._model = TextEmbedding(
                MODEL, specific_model_path=str(self.model_path), local_files_only=True,
            )
        return self._model

    def embed_query(self, query: str) -> tuple[float, ...]:
        return super().embed_query("query: " + query)

    def prepare_embedding_chunks(self, title: str, text: str) -> tuple[list[str], list[str]]:
        model = self._load_model()
        tokenizer = Tokenizer.from_str(model.model.tokenizer.to_str())
        tokenizer.no_truncation()
        tokenizer.no_padding()
        chunks, inputs = token_budget_chunks(text, "passage: " + title, tokenizer, 512)
        assert all(item.startswith("passage: ") and len(tokenizer.encode(item).ids) <= 512 for item in inputs)
        return chunks, inputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True,
                        help="Already-downloaded official pinned model snapshot; this script never downloads.")
    parser.add_argument("--seed", action="store_true", help="Populate only an empty dedicated candidate database.")
    parser.add_argument("--thresholds", default="0.34", help="Comma-separated exploratory thresholds, not calibrated production choices.")
    args = parser.parse_args()
    settings = Settings(semantic_model_name=MODEL, semantic_embedding_dimensions=384,
                        semantic_text_version="eval-e5-prefix-512-v1", semantic_search_enabled=True)
    url = make_url(settings.database_url)
    expected_archive = ROOT / ".local_eval/reader-semantic/e5-archive"
    if url.database != "reader_semantic_e5" or url.host not in {"127.0.0.1", "localhost"} or settings.archive_dir.resolve() != expected_archive:
        raise RuntimeError("Use only the dedicated local reader_semantic_e5 database and .local_eval/reader-semantic/e5-archive.")
    if not (args.model_path / "onnx/model.onnx").is_file():
        raise RuntimeError("Official model snapshot is incomplete.")
    TextEmbedding.add_custom_model(MODEL, pooling=PoolingType.MEAN, normalization=True,
                                  sources=ModelSource(hf="intfloat/multilingual-e5-small"), dim=384,
                                  model_file="onnx/model.onnx")
    run_migrations(settings.database_url)
    repository = ArchiveTaskRepository(settings.database_url)
    provider = E5EvaluationProvider(settings, args.model_path)
    started = time.perf_counter()
    provider.preload()
    preload_ms = (time.perf_counter() - started) * 1000
    service = ArchiveTaskService(repository, SingleFileArchiver(settings), YtDlpDownloader(settings),
                                 BrowserOpener(settings), provider, SemanticDocumentPreparer(180, 900, 120))
    if args.seed:
        with Session(get_engine(settings.database_url)) as session:
            if session.execute(text("SELECT count(*) FROM reader_archive_tasks")).scalar():
                raise RuntimeError("Candidate seed only accepts an empty database; nothing was deleted.")
        settings.archive_dir.mkdir(parents=True, exist_ok=True)
        for article in ARTICLES:
            name = article.task_id + ".html"
            (settings.archive_dir / name).write_text(render_article_html(article), encoding="utf-8")
            repository.create(article.task_id, article.url, name, normalized_url=article.url,
                              source_type=article.source_type, source_title=article.source_title,
                              entry_title=article.title)
            repository.mark_running(article.task_id)
            repository.mark_succeeded(article.task_id)
            repository.replace_task_tags(article.task_id, list(article.tags))
            service._index_task_semantics(article.task_id)
        print("Indexed candidate fixtures", len(ARTICLES), flush=True)
    for threshold in [float(value) for value in args.thresholds.split(",")]:
        settings.semantic_min_score = threshold
        provider._query_cache.clear()
        cases = []
        for query in QUERIES:
            started = time.perf_counter()
            response = search_archive(service, query=query.query, limit=50, offset=0,
                                      include_read=True, tags=None, content_type="all", source=None,
                                      date_from=None, exact=False, sort="relevance")
            duration = round((time.perf_counter() - started) * 1000, 2)
            cases.append(evaluate_case(query, [item.model_dump(mode="json") for item in response.items], duration))
        summary = build_summary(cases, [case["duration_ms"] for case in cases])
        payload = dict(generated_at=datetime.now(UTC).isoformat(), article_count=len(ARTICLES),
                       query_count=len(QUERIES), suite="synthetic-regression-v3-reviewed",
                       model=MODEL, revision=REVISION, threshold=threshold, preload_ms=preload_ms,
                       query_prefix="query: ", passage_prefix="passage: ", input_limit=512,
                       pooling="mean", normalization=True, summary=summary, cases=cases,
                       caveat="Exploratory in-process model comparison. Thresholds are not held-out calibrated; timings exclude HTTP.")
        output = ROOT / f".local_eval/reader-semantic/results/e5-{threshold}"
        output.mkdir(parents=True, exist_ok=True)
        (output / "semantic-eval.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        (output / "semantic-eval.md").write_text(render_markdown(payload))
        print(threshold, json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
