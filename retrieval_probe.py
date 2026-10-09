"""Compare BM25 and pinned E5 on explicitly unapproved development content.

This tool emits rankings and source IDs only. It does not answer users, choose a
route, approve content, invoke an LLM, train a model, or infer support from scores.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import re
import statistics
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from validate_content import validate_content

ROOT=Path(__file__).resolve().parent


def sha256(path):
    result=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(4*1024*1024),b''):
            result.update(chunk)
    return result.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def terms(text):
    return re.findall(r'\w+',unicodedata.normalize('NFC',text).casefold(),flags=re.UNICODE)


def bm25_scores(passages,queries,k1=1.5,b=0.75):
    counts=[Counter(terms(text)) for text in passages]
    lengths=[sum(count.values()) for count in counts]
    average=sum(lengths)/len(lengths)
    document_frequency=Counter(term for count in counts for term in count)
    result=[]
    for query in queries:
        values=[]
        for count,length in zip(counts,lengths):
            value=0.0
            for term in sorted(set(terms(query))):
                frequency=count.get(term,0)
                if not frequency:
                    continue
                df=document_frequency[term]
                idf=math.log1p((len(counts)-df+0.5)/(df+0.5))
                value+=idf*frequency*(k1+1)/(frequency+k1*(1-b+b*length/average))
            values.append(value)
        result.append(values)
    return result


def dense_scores(passages,queries):
    # Runtime is local only; public pretrained weights are never updated.
    import torch
    import torch.nn.functional as F
    from transformers import AutoModel,AutoTokenizer
    torch.set_num_threads(4)
    path=ROOT/'models/multilingual-e5-small'
    manifest=read(path/'source-manifest.json')
    metadata_path=ROOT/'results/embedding-research-20261010/intfloat--multilingual-e5-small.json'
    if not metadata_path.is_file():
        metadata_path=ROOT/'config/model-catalog/intfloat--multilingual-e5-small.json'
    pinned=read(metadata_path)
    expected=next(item for item in pinned['files'] if item['rfilename']=='model.safetensors')['lfs']['sha256']
    if manifest['revision']!=pinned['revision'] or manifest['repo_id']!=pinned['repo_id']:
        raise ValueError('E5 source differs from pinned metadata.')
    if sha256(path/'model.safetensors')!=expected:
        raise ValueError('E5 weights differ from the pinned source.')
    for name,item in manifest['files'].items():
        if sha256(path/name)!=item['sha256']:
            raise ValueError('E5 asset checksum mismatch: '+name)
    started=time.perf_counter()
    tokenizer=AutoTokenizer.from_pretrained(str(path),local_files_only=True,trust_remote_code=False)
    model=AutoModel.from_pretrained(str(path),local_files_only=True,trust_remote_code=False,use_safetensors=True)
    model.eval()
    loading=time.perf_counter()-started
    truncated=[]

    def encode(texts,prefix):
        values=[]
        for start in range(0,len(texts),8):
            current=[prefix+text for text in texts[start:start+8]]
            full=tokenizer(current,padding=False,truncation=False)['input_ids']
            truncated.extend(len(tokens)>512 for tokens in full)
            batch=tokenizer(current,padding=True,truncation=True,max_length=512,return_tensors='pt')
            with torch.inference_mode():
                hidden=model(**batch).last_hidden_state
                mask=batch['attention_mask'].unsqueeze(-1).bool()
                pooled=hidden.masked_fill(~mask,0.0).sum(dim=1)/batch['attention_mask'].sum(dim=1).unsqueeze(-1)
                values.append(F.normalize(pooled,p=2,dim=1))
        return torch.cat(values)

    started=time.perf_counter()
    documents=encode(passages,'passage: ')
    index_seconds=time.perf_counter()-started
    started=time.perf_counter()
    questions=encode(queries,'query: ')
    query_seconds=time.perf_counter()-started
    values=(questions@documents.T).tolist()
    assert sha256(path/'model.safetensors')==expected
    return values,dict(repo=pinned['repo_id'],revision=pinned['revision'],weight_sha256=expected,
        device='cpu',model_loading_seconds=loading,passage_embedding_seconds=index_seconds,
        query_batch_embedding_seconds=query_seconds,embedding_dimension=int(documents.shape[1]),
        max_tokens=512,truncated_inputs=sum(truncated),pooling='attention-masked mean + L2 normalization',
        query_prefix='query: ',passage_prefix='passage: ',training_performed=False,
        local_files_only=True,trust_remote_code=False,weight_hash_unchanged_after_inference=True,
        versions={name:importlib.metadata.version(name) for name in ('torch','transformers','safetensors')})


def rank(values,faqs):
    return [dict(faq_id=faqs[index]['faq_id'],score=float(values[index]),
                 source_refs=faqs[index]['source_refs'],approval_status=faqs[index]['approval_status'])
            for index in sorted(range(len(faqs)),key=lambda i:(-values[i],faqs[i]['faq_id']))]


def summarize(rows):
    positive=[row for row in rows if row['proposed_relevant_faq_ids']]
    negative=[row for row in rows if not row['proposed_relevant_faq_ids']]
    ranks=[next((index for index,item in enumerate(row['ranking'],1)
                 if item['faq_id'] in row['proposed_relevant_faq_ids']),None) for row in positive]
    return dict(label_status='assistant_proposed_not_human_approved',positive_cases=len(positive),
        top1_hit_rate=sum(r==1 for r in ranks)/len(ranks),
        top3_hit_rate=sum(r is not None and r<=3 for r in ranks)/len(ranks),
        mean_reciprocal_rank=statistics.mean(1/r if r else 0 for r in ranks),
        negative_cases=len(negative),
        negative_top_scores=[dict(id=row['id'],faq_id=row['ranking'][0]['faq_id'],score=row['ranking'][0]['score']) for row in negative],
        abstention_implemented=False,score_is_probability=False,production_quality_accepted=False)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='Хөгжүүлэлтийн draft FAQ хайлт; хариулт өгөхгүй')
    parser.add_argument('--allow-draft',action='store_true')
    parser.add_argument('--backend',choices=['bm25','both'],default='both')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'results/retrieval-probe-20261010')
    args=parser.parse_args()
    if not args.allow_draft:
        parser.error('Draft content requires explicit --allow-draft; this is not an approved answer service.')
    output=args.output_dir.resolve()
    if not output.is_relative_to((ROOT/'results').resolve()):
        parser.error('Require output directory inside project results.')
    if output.exists():
        parser.error('Output directory exists. Use a fresh run directory; preserve prior evidence.')
    content_path=ROOT/'data/content-draft-v1.json'
    cases_path=ROOT/'data/retrieval-dev-cases-20261010.json'
    content=read(content_path)
    errors=validate_content(content)
    if errors:
        raise ValueError(errors)
    faqs=content['faqs']
    cases=read(cases_path)['cases']
    if not faqs or len({faq['faq_id'] for faq in faqs})!=len(faqs):
        raise ValueError('Need a nonempty uniquely identified FAQ corpus.')
    if len({case['id'] for case in cases})!=len(cases):
        raise ValueError('Duplicate development case ID.')
    faq_ids={faq['faq_id'] for faq in faqs}
    if any(set(case['proposed_relevant_faq_ids'])-faq_ids for case in cases):
        raise ValueError('Proposed reference targets missing from the corpus.')
    passages=[' '.join([faq['question'],*faq['question_aliases'],faq['answer'],faq['scope']]) for faq in faqs]
    queries=[case['question'] for case in cases]
    started=time.perf_counter()
    matrices={'bm25':bm25_scores(passages,queries)}
    protocol=dict(created_at=datetime.now(timezone.utc).isoformat(),client_date='2026-10-10',
        code_sha256=sha256(Path(__file__)),
        content_sha256=sha256(content_path),cases_sha256=sha256(cases_path),
        faq_ids=[faq['faq_id'] for faq in faqs],draft_content_explicitly_allowed=True,
        label_status='assistant_proposed_not_human_approved',approved_gold=False,final_test=False,
        bm25=dict(k1=1.5,b=0.75,idf='log1p((N-df+0.5)/(df+0.5))',query_term_weight='sorted unique query terms',
                  tokenizer='NFC/casefold Unicode word tokens; no morphology or alias expansion',
                  batch_seconds=time.perf_counter()-started),
        answer_generation_performed=False,llm_calls=0,router_implemented=False,
        private_audio_used=False,training_performed=False)
    if args.backend=='both':
        print('Локал E5: Монгол асуулт/FAQ-г embedding болгож харьцуулна; training хийхгүй.',flush=True)
        matrices['e5'],protocol['e5']=dense_scores(passages,queries)
    result={}
    summaries={}
    for name,matrix in matrices.items():
        rows=[dict(**case,ranking=rank(values,faqs)) for case,values in zip(cases,matrix)]
        result[name]=rows
        summaries[name]=summarize(rows)
    output.mkdir()
    report=dict(protocol=protocol,summary=summaries,rows=result,
        limitations=['Five FAQ candidates only; top5 is trivial and not reported.',
            'Assistant-authored development paraphrases and labels, not observed user questions or approved gold.',
            'FAQ and school sources remain drafts; corpus does not prove current factual correctness.',
            'Negative controls always have a closest result; similarity does not prove answer support.',
            'No deployed abstention threshold or router; no generated or served answer.',
            'Timings are one batch, not controlled end-to-end latency benchmarks.'])
    with (output/'comparison.json').open('x',encoding='utf-8') as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2)
    print(json.dumps(summaries,ensure_ascii=False,indent=2))
    print('Saved: '+str(output/'comparison.json'))


if __name__=='__main__':
    main()
