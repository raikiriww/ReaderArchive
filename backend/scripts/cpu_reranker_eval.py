"""Read-only, local CPU reranker experiment on an explicitly supplied copied DB.

Inputs/outputs contain private saved-article text: keep them in an ignored local
directory. Download models separately; inference always uses local files only.
This is a source-constructed diagnostic, not a blind relevance benchmark.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def rss_mb() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(value / (1024**2 if sys.platform == "darwin" else 1024), 1)


def sentence_window(body: str, content: str, budget: int = 650) -> str:
    """Generic complete-sentence source window, no answer-aware boundaries."""
    from app.search_passages import source_window
    passage = source_window(body, content, width=budget)
    return passage.text if passage else content


def prepare(args: argparse.Namespace) -> None:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from app.core.config import Settings
    from app.semantic import LocalEmbeddingProvider

    info = conninfo_to_dict(args.database_url)
    if info.get("host") not in {"127.0.0.1", "localhost"} or not info.get("dbname", "").startswith("reader_servercopy_"):
        raise SystemExit("Only an explicitly named localhost reader_servercopy_* database is permitted.")
    cases = json.loads((args.copy_dir / "real-queries.json").read_text())["cases"]
    next_stage_path = args.copy_dir / "next-stage-cases.json"
    evidence_requirements = {c["id"]: c.get("excerpt_must_contain") for c in json.loads(next_stage_path.read_text())["cases"]} if next_stage_path.exists() else {}
    baseline = json.loads((args.copy_dir / "real-query-results.json").read_text())
    settings = Settings(_env_file=None, semantic_model_dir=ROOT / ".local_verify/search-models")
    embedder = LocalEmbeddingProvider(settings)
    embedder.preload()
    output = dict(created_at=datetime.now(UTC).isoformat(), caveat="Source-constructed targeted checks; not user accuracy or blind evaluation. No database writes or remote inference.", cases=[])
    with psycopg.connect(args.database_url, options="-c default_transaction_read_only=on") as conn:
        assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        for case, old in zip(cases, baseline["results"], strict=True):
            assert case["id"] == old["id"]
            target = case["expected_task_ids"][0]
            title, body = conn.execute("SELECT coalesce(t.custom_title,t.entry_title,t.video_title,''), d.content FROM reader_archive_tasks t JOIN reader_archive_search_documents d ON d.task_id=t.id WHERE t.id=%s", (target,)).fetchone()
            selected = []
            for rank, item in enumerate(old["top_results"][:10], 1):
                selected.append(dict(task_id=item["task_id"], title=item["title"], content=item["search_match"]["excerpt"], origin="old_api_excerpt", baseline_rank=rank))
            vector = embedder.embed_query(case["query"])
            literal = "[" + ",".join(str(float(v)) for v in vector) + "]"
            rows = conn.execute("""SELECT c.chunk_index,c.content,1-(c.embedding <=> %s::vector) AS score
              FROM reader_archive_semantic_chunks c JOIN reader_archive_semantic_indexes i
              ON i.task_id=c.task_id AND i.model_name=c.model_name AND i.document_hash=c.document_hash
              WHERE c.task_id=%s AND i.text_version='token-body-v2' AND i.status='indexed'
              ORDER BY score DESC,c.chunk_index""", (literal, target)).fetchall()
            controls = [dict(task_id=target, title=title, content=c, origin="target_saved_chunk_control", chunk_index=idx, embedding_score=float(score), within_article_rank=rank)
                        for rank, (idx, c, score) in enumerate(rows, 1)]
            # Full target chunks are an oracle control, never labelled retrieval recall.
            for row in controls[:3]:
                selected.append(dict(**{k: v for k, v in row.items() if k not in {"content", "origin"}}, content=sentence_window(body, row["content"]), origin="target_top3_source_window_control"))
            output["cases"].append(dict(id=case["id"], kind=case["kind"], query=case["query"], expected_task_id=target, expected_title=title, expected_quote=evidence_requirements.get(case["id"]) or case["evidence"]["quote"], baseline_rank=old["target_rank"], baseline_manual_pass=old["passed"], pool=selected, target_chunks=controls))
            if args.expanded and case["id"] in args.full_target_cases:
                candidates = conn.execute("""WITH scored AS (
                  SELECT c.task_id,c.chunk_index,c.content,1-(c.embedding <=> %s::vector) AS score,
                  row_number() OVER(PARTITION BY c.task_id ORDER BY c.embedding <=> %s::vector,c.chunk_index) AS passage_rank
                  FROM reader_archive_semantic_chunks c JOIN reader_archive_semantic_indexes i
                  ON i.task_id=c.task_id AND i.model_name=c.model_name AND i.document_hash=c.document_hash
                  WHERE i.text_version='token-body-v2' AND i.status='indexed'),
                  articles AS (SELECT task_id,score,row_number() OVER(ORDER BY score DESC,task_id) AS article_rank FROM scored WHERE passage_rank=1)
                  SELECT s.task_id,s.chunk_index,s.content,s.score,s.passage_rank,a.article_rank,
                  coalesce(t.custom_title,t.entry_title,t.video_title,''),d.content
                  FROM scored s JOIN articles a ON a.task_id=s.task_id
                  JOIN reader_archive_tasks t ON t.id=s.task_id JOIN reader_archive_search_documents d ON d.task_id=s.task_id
                  WHERE a.article_rank<=200 AND s.passage_rank<=3 ORDER BY a.article_rank,s.passage_rank""", (literal,literal)).fetchall()
                expanded = []
                seen = set()
                for tid,idx,content,score,prank,arank,ctitle,cbody in candidates:
                    window = sentence_window(cbody,content)
                    if (tid,window) in seen:
                        continue
                    seen.add((tid,window))
                    expanded.append(dict(task_id=tid,title=ctitle,content=window,origin="actual_embedding_top200_top3_source_window",chunk_index=idx,embedding_score=float(score),within_article_rank=prank,baseline_article_rank=arank))
                output["cases"][-1]["expanded_pool"] = expanded
            print("prepared", case["id"], flush=True)
    save(args.output / "inputs.json", output)


def run(args: argparse.Namespace) -> None:
    from app.reranking import LocalRerankerProvider
    import torch
    import transformers

    data = json.loads((args.output / "inputs.json").read_text())
    provider = LocalRerankerProvider(model_name=str(args.model.resolve()), cache_dir=args.model.parent, num_threads=args.threads, batch_size=args.batch_size, max_length=args.max_length, max_passages=1000, cache_size=0, local_files_only=True)
    result = dict(created_at=datetime.now(UTC).isoformat(), caveat=data["caveat"], platform=platform.platform(), machine=platform.machine(), logical_cpus=os.cpu_count(), torch=torch.__version__, transformers=transformers.__version__, threads=args.threads, batch_size=args.batch_size, max_length=args.max_length, model=str(args.model.resolve()), benchmarks=[], cases=[])
    started = time.perf_counter()
    provider.preload()
    result.update(load_seconds=round(time.perf_counter()-started, 4), peak_rss_after_load_mb=rss_mb())
    if args.quantize:
        started = time.perf_counter()
        engine = "qnnpack" if platform.machine() == "arm64" else "x86"
        torch.backends.quantized.engine = engine
        provider._model = torch.ao.quantization.quantize_dynamic(provider._model, {torch.nn.Linear}, dtype=torch.qint8)
        result.update(quantization="dynamic_int8_linear", quantization_engine=engine, quantization_seconds=round(time.perf_counter()-started,4), peak_rss_after_quantization_mb=rss_mb())
    report_path = args.output / args.result_name
    save(report_path, result)
    print("MODEL_READY", json.dumps({k: result[k] for k in ["load_seconds", "peak_rss_after_load_mb", "machine"]}), flush=True)
    passages = [p["title"] + "\n" + p["content"] for c in data["cases"] for p in c["pool"]]
    for count in [1, 8, 32]:
        started = time.perf_counter()
        values = provider.score(data["cases"][3]["query"], passages[:count])
        seconds = time.perf_counter()-started
        counts = [len(provider._tokenizer(data["cases"][3]["query"], text, truncation=False)["input_ids"]) for text in passages[:count]]
        item = dict(pairs=count, seconds=round(seconds, 4), seconds_per_pair=round(seconds/count, 4), peak_rss_mb=rss_mb(), score_count=len(values), input_tokens_min=min(counts),input_tokens_max=max(counts),input_tokens_mean=round(sum(counts)/len(counts),1), cache_enabled=False,first_forward=count==1)
        result["benchmarks"].append(item)
        save(report_path, result)
        print("BENCHMARK", json.dumps(item), flush=True)
    if args.benchmark_only:
        return
    def score_pool(case: dict, pool: list[dict]) -> tuple[list[dict], float, int]:
        started = time.perf_counter()
        prepared = []
        for source_index, passage in enumerate(pool):
            text = passage["title"]+"\n"+passage["content"]
            for part_index, piece in enumerate(provider.split_passage(case["query"], text)):
                prepared.append(dict(**passage,source_index=source_index,part_index=part_index,model_input=piece,input_tokens=provider._pair_size(case["query"],piece),truncated=False,exact_evidence_quote_present=case["expected_quote"] in piece))
        scores = provider.score(case["query"], [p["model_input"] for p in prepared])
        ranked = sorted([dict(**p,raw_logit=s) for p,s in zip(prepared,scores,strict=True)],key=lambda p:-p["raw_logit"])
        return ranked,time.perf_counter()-started,len(prepared)
    ordered_cases = sorted(data["cases"], key=lambda c: c["id"] not in args.full_target_cases)
    if args.case_ids:
        ordered_cases = [c for c in ordered_cases if c["id"] in args.case_ids]
    for case in ordered_cases:
        # Compare a fixed prior-result pool, then separate target-injected controls.
        pool = case["pool"] + (case["target_chunks"] if case["id"] in args.full_target_cases else [])
        ranked, seconds, pair_count = score_pool(case,pool)
        old_pool = [p for p in ranked if p["origin"] == "old_api_excerpt"]
        old_articles = list(dict.fromkeys(p["task_id"] for p in old_pool))
        item = {k:v for k,v in case.items() if k not in {"pool", "target_chunks", "expanded_pool"}}
        item.update(seconds=round(seconds,4), pair_count=pair_count, original_passages=len(pool), peak_rss_mb=rss_mb(), old_pool_target_rank=old_articles.index(case["expected_task_id"])+1 if case["expected_task_id"] in old_articles else None, old_pool_ranked=old_pool, augmented_control_ranked=ranked)
        result["cases"].append(item)
        save(report_path, result)
        print("CASE", case["id"], "seconds", round(seconds,2), "oldpooltarget", item["old_pool_target_rank"], "controltop", ranked[0]["task_id"], ranked[0]["origin"], flush=True)
    if args.expanded:
        result["expanded_cases"] = []
        for case in ordered_cases:
            if "expanded_pool" not in case:
                continue
            pool = case["expanded_pool"]
            ranked, seconds, pair_count = score_pool(case,pool)
            articles = list(dict.fromkeys(p["task_id"] for p in ranked))
            target_rank = articles.index(case["expected_task_id"])+1 if case["expected_task_id"] in articles else None
            result["expanded_cases"].append(dict(id=case["id"],query=case["query"],seconds=round(seconds,4),pairs=pair_count,original_passages=len(pool),target_article_rank=target_rank,ranked=ranked,peak_rss_mb=rss_mb()))
            save(report_path, result)
            print("EXPANDED",case["id"],"seconds",round(seconds,2),"pairs",len(pool),"target_rank",target_rank,flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("--copy-dir", type=Path, default=ROOT / ".local_verify/server-copy-20260905")
    parser.add_argument("--output", type=Path, default=ROOT / ".local_verify/server-copy-20260905/reranker-eval")
    parser.add_argument("--database-url", default=os.environ.get("RERANKER_EVAL_DATABASE_URL", ""))
    parser.add_argument("--model", type=Path, default=ROOT / ".local_verify/search-models-reranker/verified-bge-v2-m3")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--benchmark-only", action="store_true")
    parser.add_argument("--expanded", action="store_true", help="Also evaluate actual unmodified top200 articles with their top3 passages; expensive.")
    parser.add_argument("--quantize", action="store_true", help="Controlled CPU dynamic int8 Linear experiment; does not mutate saved model weights.")
    parser.add_argument("--result-name", default="results.json")
    parser.add_argument("--case-ids", nargs="*", help="Optional fixed case subset; omitted means all prepared cases.")
    parser.add_argument("--full-target-cases", nargs="*", default=["meaning-review-burden", "distractor-cache-memory"])
    arguments = parser.parse_args()
    (prepare if arguments.action == "prepare" else run)(arguments)
