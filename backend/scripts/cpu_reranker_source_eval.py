"""CPU reranker quality controls using explicit local source windows.

No network or database access. Inputs are saved locally by a separate read-only
preparation step. Target-injected controls must never be reported as retrieval
recall or end-to-end search quality.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import resource
import re
import sys
import time
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
try:
    from reranking import LocalRerankerProvider
    from search_passages import SourcePassage, evidence_windows
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.reranking import LocalRerankerProvider
    from app.search_passages import SourcePassage, evidence_windows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--precisions", nargs="+", choices=["none", "int8", "auto"], default=["none"])
    parser.add_argument("--archive-dir", type=Path, help="Read existing original archives with a coordinates-only input manifest.")
    parser.add_argument("--summary-only", action="store_true", help="Omit every source passage/quote from output; report only IDs, scores and booleans.")
    parser.add_argument("--validate-only", action="store_true", help="Verify source hashes and coordinates without loading a model.")
    args = parser.parse_args()
    data = json.loads(args.inputs.read_text())
    if data.get("coordinates_only"):
        if args.archive_dir is None:
            raise SystemExit("A coordinates-only manifest requires --archive-dir.")
        import trafilatura
        bodies = {}
        for file_name, metadata in data["files"].items():
            if Path(file_name).name != file_name:
                raise ValueError("Archive file names must be basenames.")
            source=args.archive_dir/file_name
            raw=source.read_bytes()
            assert hashlib.sha256(raw).hexdigest()==metadata["file_sha256"],"Original archive hash mismatch."
            extracted=trafilatura.extract(raw.decode("utf-8",errors="ignore"),include_comments=False,include_formatting=False,include_images=False,include_links=False,favor_recall=True)
            text=re.sub(r"\n{3,}","\n\n","\n".join(" ".join(line.split()) for line in (extracted or "").splitlines())).strip()
            assert hashlib.sha256(text.encode()).hexdigest()==metadata["body_sha256"],"Extracted source hash mismatch."
            bodies[file_name]=text
        for case in data["cases"]:
            case["answer"]=bodies[case["answer_file"]][case["answer_start"]:case["answer_end"]]
            for entry in case["pool"]:
                entry["content"]=bodies[entry["file_name"]][entry["start"]:entry["end"]]
    if args.validate_only:
        print(json.dumps(dict(source_hashes_verified=bool(data.get("coordinates_only")),cases=len(data["cases"]),passages=sum(len(c["pool"]) for c in data["cases"]))))
        return
    report = dict(caveat=data["caveat"], model=str(args.model), pure_body_inputs=True,
                  max_length=512,threads=4,batch_size=2,cache_enabled=False,runs=[])
    for precision in args.precisions:
        started = time.perf_counter()
        provider = LocalRerankerProvider(model_name=str(args.model.resolve()),cache_dir=args.model.parent / "hf-cache",num_threads=4,batch_size=2,max_length=512,max_passages=1000,cache_size=0,local_files_only=True,quantization=precision)
        provider.preload()
        run = dict(precision=precision,load_seconds=time.perf_counter()-started,cases=[])
        for case in data["cases"]:
            started=time.perf_counter()
            pairs=[]
            for entry in case["pool"]:
                for piece in provider.split_passage(case["query"],entry["content"]):
                    pairs.append(dict(**entry,model_input=piece,input_tokens=provider._pair_size(case["query"],piece),has_answer=case["answer"] in piece))
            scores=provider.score(case["query"],[p["model_input"] for p in pairs])
            ranked=sorted([dict(**p,logit=s) for p,s in zip(pairs,scores,strict=True)],key=lambda p:-p["logit"])
            target=next(p for p in ranked if p["task_id"]==case["expected_task_id"])
            articles=list(dict.fromkeys(p["task_id"] for p in ranked))
            passage_seconds=time.perf_counter()-started
            quotes=[]
            for quote in evidence_windows(SourcePassage(target["model_input"],0,len(target["model_input"]))):
                for piece in provider.split_passage(case["query"],quote.text):
                    quotes.append(dict(content=piece,input_tokens=provider._pair_size(case["query"],piece),has_answer=case["answer"] in piece))
            started=time.perf_counter()
            quote_scores=provider.score(case["query"],[q["content"] for q in quotes])
            quote_ranked=sorted([dict(**q,logit=s) for q,s in zip(quotes,quote_scores,strict=True)],key=lambda q:-q["logit"])
            result=dict(id=case["id"],query=case["query"],expected_task_id=case["expected_task_id"],answer=case["answer"],passage_pairs=len(pairs),passage_seconds=passage_seconds,quote_pairs=len(quotes),quote_seconds=time.perf_counter()-started,target_article_rank=articles.index(case["expected_task_id"])+1,top_passage_has_answer=ranked[0]["has_answer"],selected_target_quote_has_answer=quote_ranked[0]["has_answer"],ranked=ranked,quote_ranked=quote_ranked)
            if args.summary_only:
                result.pop("answer")
                result["ranked"]=[{k:v for k,v in p.items() if k not in {"content","model_input"}} for p in ranked]
                result["quote_ranked"]=[{k:v for k,v in q.items() if k!="content"} for q in quote_ranked]
            run["cases"].append(result)
            print(json.dumps({k:result[k] for k in ["id","passage_pairs","passage_seconds","target_article_rank","top_passage_has_answer","selected_target_quote_has_answer"]}|dict(precision=precision)),flush=True)
        run["peak_rss_mib"]=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform=="darwin" else 1024)
        report["runs"].append(run)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        del provider
        gc.collect()


if __name__ == "__main__":
    main()
