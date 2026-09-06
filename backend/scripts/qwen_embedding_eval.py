"""Read-only CPU embedding comparison on a named local server-data copy.

Download public model files separately. All article processing is offline. This
source-constructed directed check is not blind relevance/accuracy evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false',
                  OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
REVISION = '97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3'
MODEL = ROOT / '.local_verify/search-models-qwen/models--Qwen--Qwen3-Embedding-0.6B/snapshots' / REVISION
INSTRUCTION = 'Given a web search query, retrieve relevant passages that answer the query'


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def chunks_for_document(tokenizer, title, body, budget=512):
    """Use the identical source packing as the candidate production provider."""
    from app.qwen_embedding import prepare_qwen_chunks
    return [dict(start=chunk.start, end=chunk.end, content=chunk.content,
                 input=chunk.input_text, tokens=chunk.token_count)
            for chunk in prepare_qwen_chunks(tokenizer, title, body, budget)]


def display_title(custom_title, entry_title, video_title, url):
    """Match ArchiveTaskRepository._to_task, including blank/title URL fallback."""
    title = next((str(value).strip() for value in (custom_title, entry_title, video_title)
                  if str(value or '').strip()), '')
    if title:
        return title
    parsed = urlparse(url)
    path = parsed.path.rstrip('/')
    return f'{parsed.netloc}{path}' if parsed.netloc else url


def prepare(args):
    import numpy as np
    import psycopg
    from fastembed import TextEmbedding
    from psycopg.conninfo import conninfo_to_dict
    from transformers import AutoTokenizer
    info = conninfo_to_dict(args.database_url)
    if info.get('host') not in {'127.0.0.1','localhost'} or not info.get('dbname','').startswith('reader_servercopy_'):
        raise SystemExit('Only localhost reader_servercopy_* is allowed')
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, padding_side='left')
    cases = json.loads((args.copy_dir / 'real-queries.json').read_text())['cases']
    old_api = {item['id']: item['target_rank'] for item in json.loads((args.copy_dir / 'real-query-results.json').read_text())['results']}
    with psycopg.connect(args.database_url, options='-c default_transaction_read_only=on') as conn:
        assert conn.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
        document_rows = conn.execute("""SELECT t.id,t.custom_title,t.entry_title,t.video_title,t.url,d.content
          FROM reader_archive_tasks t JOIN reader_archive_search_documents d ON d.task_id=t.id
          WHERE d.status='ready' ORDER BY t.id""").fetchall()
        old_chunks = conn.execute("""SELECT c.task_id,c.chunk_index,c.embedding::text FROM reader_archive_semantic_chunks c
          JOIN reader_archive_semantic_indexes i ON i.task_id=c.task_id AND i.model_name=c.model_name AND i.document_hash=c.document_hash
          WHERE i.status='indexed' AND i.text_version='token-body-v2'
          AND c.model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2' ORDER BY c.task_id,c.chunk_index""").fetchall()
    docs = [(row[0], display_title(*row[1:5]), row[5]) for row in document_rows]
    chunks = []
    started = time.perf_counter()
    for task_id, title, body in docs:
        for index, chunk in enumerate(chunks_for_document(tokenizer,title,body,args.max_length)):
            chunks.append(dict(task_id=task_id,title=title,chunk_index=index,**chunk))
    baseline_model = TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        cache_dir=str(ROOT / '.local_verify/search-models'),local_files_only=True,threads=4)
    old_vectors = np.array([json.loads(row[2]) for row in old_chunks],dtype=np.float32)
    old_vectors /= np.linalg.norm(old_vectors,axis=1,keepdims=True)
    query_vectors = list(baseline_model.embed([case['query'] for case in cases]))
    for case, vector in zip(cases,query_vectors,strict=True):
        scores = old_vectors @ (vector / np.linalg.norm(vector))
        articles = {}
        for row, score in zip(old_chunks,scores,strict=True):
            articles[row[0]] = max(articles.get(row[0],-1),float(score))
        order = sorted(articles,key=lambda tid:(-articles[tid],tid))
        target = case['expected_task_ids'][0]
        case['minilm_raw_rank'] = order.index(target)+1 if target in order else None
        case['minilm_raw_score'] = articles.get(target)
        case['old_api_rank'] = old_api[case['id']]
    data = dict(model='Qwen/Qwen3-Embedding-0.6B',revision=REVISION,max_length=args.max_length,
        instruction=INSTRUCTION,document_count=len(docs),chunk_count=len(chunks),body_characters=sum(len(row[2]) for row in docs),
        title_resolution='Repository display_title precedence: stripped custom, entry, video title; otherwise URL host and path.',
        preparation_seconds=time.perf_counter()-started,cases=cases,chunks=chunks,
        caveat='Directed known-source checks, not a blind benchmark. Model and chunking both changed; not an isolated model-only comparison.',
        chunking='Natural sentence packing <=512 tokens including title (first 64 title tokens), <=64-token sentence overlap; no query-aware boundaries.')
    save(args.output / 'inputs.json',data)
    print(json.dumps({key:value for key,value in data.items() if key not in {'cases','chunks'}},ensure_ascii=False),flush=True)


def run(args):
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    data = json.loads((args.output / 'inputs.json').read_text())
    tokenizer = AutoTokenizer.from_pretrained(args.model,local_files_only=True,padding_side='left')
    started = time.perf_counter()
    model = AutoModel.from_pretrained(args.model,local_files_only=True,torch_dtype=torch.float32,attn_implementation='sdpa').eval().to('cpu')
    results_path = args.output / ('results.json' if args.dimensions == 1024 else f'results-{args.dimensions}.json')
    report = dict(dimensions=args.dimensions, model=data['model'],revision=REVISION,device='cpu',dtype='float32',threads=4,batch_size=args.batch_size,
        platform=platform.platform(),torch=torch.__version__,document_count=data['document_count'],chunk_count=data['chunk_count'],
        model_load_seconds=time.perf_counter()-started,caveat=data['caveat'],chunking=data['chunking'],benchmarks=[])
    def encode(texts):
        batch = tokenizer(texts,padding=True,truncation=False,return_tensors='pt')
        assert batch['input_ids'].shape[1] <= args.max_length
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state[:,-1]
            return torch.nn.functional.normalize(hidden,p=2,dim=1).numpy()
    public_examples = [f'Instruct: {INSTRUCTION}\nQuery:{query}' for query in
        ['What is the capital of China?', 'Explain gravity']]
    public_examples.extend(['The capital of China is Beijing.',
        'Gravity is a force that attracts two bodies towards each other. It gives weight to physical objects and is responsible for the movement of planets around the sun.'])
    public_vectors = encode(public_examples)
    public_scores = public_vectors[:2] @ public_vectors[2:].T
    reference_scores = np.array([[.764556825,.141425088],[.135497361,.599954963]])
    report['official_example_scores'] = public_scores.tolist()
    report['official_example_max_abs_error'] = float(np.max(np.abs(public_scores-reference_scores)))
    assert report['official_example_max_abs_error'] < .01
    texts = [chunk['input'] for chunk in data['chunks']]
    # Fixed evenly spaced real samples, not chosen by their retrieval score.
    sample_ids = [min(len(texts)-1,index*len(texts)//8) for index in range(8)]
    for count in [1,4,8]:
        sample_texts = [texts[index] for index in sample_ids[:count]]
        start = time.perf_counter()
        encode(sample_texts)
        elapsed = time.perf_counter()-start
        report['benchmarks'].append(dict(count=count,seconds=elapsed,seconds_per_chunk=elapsed/count,
            token_counts=[len(tokenizer.encode(value)) for value in sample_texts]))
        save(results_path,report)
        print('BENCHMARK',json.dumps(report['benchmarks'][-1]),flush=True)
    if args.benchmark_only:
        return
    # Resume only vectors created for the exact inputs/model/settings.
    fingerprint = hashlib.sha256((args.output / 'inputs.json').read_bytes()).hexdigest()
    checkpoint = args.output / 'checkpoint.json'
    vectors_path = args.output / 'vectors.npy'
    done = 0
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text())
        assert saved['fingerprint'] == fingerprint
        done = saved['done']
        vectors = np.lib.format.open_memmap(vectors_path,mode='r+')
    else:
        vectors = np.lib.format.open_memmap(vectors_path,mode='w+',dtype=np.float32,shape=(len(texts),1024))
    start = time.perf_counter()
    previous_done = done
    # Stable source order keeps checkpoint positions independent of query results.
    for offset in range(done,len(texts),args.batch_size):
        batch = texts[offset:offset+args.batch_size]
        vectors[offset:offset+len(batch)] = encode(batch)
        if (offset//args.batch_size)%8 == 0 or offset+len(batch)==len(texts):
            vectors.flush()
            completed = offset+len(batch)
            save(checkpoint,dict(fingerprint=fingerprint,done=completed))
            print('INDEX',completed,'/',len(texts),'elapsed',round(time.perf_counter()-start,1),flush=True)
    report['index_seconds_this_run'] = time.perf_counter()-start
    report['index_chunks_this_run'] = len(texts)-previous_done
    report['cases'] = []
    projected_vectors = np.asarray(vectors)[:, :args.dimensions]
    projected_vectors = projected_vectors / np.linalg.norm(projected_vectors, axis=1, keepdims=True)
    for case in data['cases']:
        start = time.perf_counter()
        query = f'Instruct: {INSTRUCTION}\nQuery:{case["query"]}'
        query_vector = encode([query])[0]
        query_seconds = time.perf_counter()-start
        query_vector = query_vector[:args.dimensions]
        query_vector = query_vector / np.linalg.norm(query_vector)
        scores = projected_vectors @ query_vector
        best = {}
        for idx,(chunk,score) in enumerate(zip(data['chunks'],scores,strict=True)):
            if chunk['task_id'] not in best or score > best[chunk['task_id']][0]:
                best[chunk['task_id']] = (float(score),idx)
        order = sorted(best,key=lambda tid:(-best[tid][0],tid))
        target = case['expected_task_ids'][0]
        target_rank = order.index(target)+1 if target in order else None
        target_score,target_idx = best.get(target,(None,None))
        item = dict(id=case['id'],query=case['query'],expected_task_id=target,target_rank=target_rank,target_score=target_score,
            minilm_raw_rank=case['minilm_raw_rank'],minilm_raw_score=case['minilm_raw_score'],old_api_rank=case['old_api_rank'],
            query_seconds=query_seconds,target_chunk=data['chunks'][target_idx] if target_idx is not None else None,
            top20=[dict(task_id=tid,score=best[tid][0],chunk=data['chunks'][best[tid][1]]) for tid in order[:20]])
        report['cases'].append(item)
        save(results_path,report)
        print('CASE',case['id'],'target',target_rank,'old',case['minilm_raw_rank'],'query_seconds',round(query_seconds,3),flush=True)
    report['peak_rss_mb'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024**2 if platform.system()=='Darwin' else 1024)
    save(results_path,report)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','run'])
    parser.add_argument('--copy-dir',type=Path,default=ROOT/'.local_verify/server-copy-20260905')
    parser.add_argument('--output',type=Path,default=ROOT/'.local_verify/server-copy-20260905/qwen-embedding-eval')
    parser.add_argument('--model',type=Path,default=MODEL)
    parser.add_argument('--database-url',default=os.environ.get('QWEN_EVAL_DATABASE_URL',''))
    parser.add_argument('--max-length',type=int,default=512)
    parser.add_argument('--dimensions',type=int,choices=[384,1024],default=1024)
    parser.add_argument('--batch-size',type=int,default=4)
    parser.add_argument('--benchmark-only',action='store_true')
    args=parser.parse_args()
    (prepare if args.action=='prepare' else run)(args)
