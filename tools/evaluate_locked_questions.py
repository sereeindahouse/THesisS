"""Check, lock and run the W04 question set; scores only after a person has locked it."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_SET=ROOT/'data/rag-locked-questions-20261102.json'
EXPECTED_COUNTS=dict(answerable=20,unanswerable=10,reception=10)
RETRIEVAL_MODES=('bm25','e5','rrf','production')
SCOPE=('Assistant-drafted, person-locked development set. Value presence is not full answer correctness; '
    'review each answer by hand before reporting. Not general accuracy.')


def normalize(text):
    return ' '.join(unicodedata.normalize('NFC',text).casefold().split())


def questions_sha256(questions):
    text=json.dumps(questions,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(text.encode()).hexdigest()


def value_present(value,text):
    """A list means any one wording counts; a plain number must not match inside a longer number."""
    if isinstance(value,list):
        return any(value_present(item,text) for item in value)
    wanted,text=normalize(value),normalize(text)
    if wanted.isdigit():
        return re.search(rf'(?<!\d){re.escape(wanted)}(?!\d)',text) is not None
    return wanted in text


def missing_values(question,answer):
    return [value for value in question.get('required_values',[]) if not value_present(value,answer or '')]


def validate_shape(data):
    """Return problems in the set itself, without touching the database or the system."""
    questions=data.get('questions',[])
    problems=[]
    counts={kind:sum(q.get('kind')==kind for q in questions) for kind in EXPECTED_COUNTS}
    if counts!=EXPECTED_COUNTS:
        problems.append(f'counts {counts} differ from {EXPECTED_COUNTS}')
    seen=set()
    for q in questions:
        key=normalize(q.get('query',''))
        if not key or key in seen:
            problems.append(f"{q.get('id')}: empty or repeated query")
        seen.add(key)
        if q.get('kind')=='answerable' or q.get('expected_now')=='answerable':
            if not q.get('required_values') or not q.get('support') or not q.get('answer_mn'):
                problems.append(f"{q.get('id')}: needs required_values, support and answer_mn")
        if q.get('kind')=='unanswerable' and not q.get('why_mn'):
            problems.append(f"{q.get('id')}: needs why_mn")
    return problems


def stored_texts(database):
    """Latest page text plus extracted document and tab payloads, keyed by URL."""
    connection=sqlite3.connect(f'file:{Path(database).as_posix()}?mode=ro',uri=True)
    try:
        texts={}
        for url,text in connection.execute('select url,text from pages order by version'):
            texts[url]=text
        for table in ('document_extractions','client_tab_extractions'):
            for url,payload in connection.execute(f'select url,payload_json from {table}'):
                texts[url]=texts.get(url,'')+'\n'+json.dumps(json.loads(payload),ensure_ascii=False)
        return texts
    finally:
        connection.close()


def validate_sources(questions,texts):
    """Every promised phrase must exist in its page; every absence term must find nothing."""
    problems=[]
    for q in questions:
        for item in q.get('support',[]):
            if normalize(item['phrase']) not in normalize(texts.get(item['url'],'')):
                problems.append(f"{q['id']}: phrase not in {item['url']}")
        for pattern in q.get('absence_terms',[]):
            for url,text in texts.items():
                found=re.search(pattern,normalize(text),re.IGNORECASE|re.DOTALL)
                if found:
                    problems.append(f"{q['id']}: absence term matched {url}: {found.group(0)[:120]}")
    return problems


def lock(path,locked_by,now=None):
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('status')=='locked':
        raise ValueError('Set is already locked; a changed set needs a new file.')
    if not isinstance(locked_by,str) or not locked_by.strip():
        raise ValueError('A person must be named when locking.')
    problems=validate_shape(data)
    if problems:
        raise ValueError('; '.join(problems))
    data.update(status='locked',locked_by=locked_by.strip(),questions_sha256=questions_sha256(data['questions']),
        locked_at=(now or datetime.now(timezone.utc)).isoformat())
    path.write_text(json.dumps(data,ensure_ascii=False,indent=1)+'\n',encoding='utf-8',newline='\n')
    return data


def require_locked(data):
    if data.get('status')!='locked' or not data.get('locked_by'):
        raise ValueError('Set is not locked. A person must review and lock it before any run.')
    if data.get('questions_sha256')!=questions_sha256(data['questions']):
        raise ValueError('Questions changed after locking.')


def support_rank(question,candidates):
    for rank,candidate in enumerate(candidates,1):
        for item in question['support']:
            if candidate['url']==item['url'] and normalize(item['phrase']) in normalize(candidate['text']):
                return rank
    return None


def score_retrieval(questions,search,modes=RETRIEVAL_MODES):
    """Count how often the right passage reaches the top 1, 3 and 5 for each search method."""
    answerable=[q for q in questions if q['kind']=='answerable']
    report={}
    for mode in modes:
        ranks={q['id']:support_rank(q,search(q['query'],mode)) for q in answerable}
        report[mode]=dict(cases=len(answerable),ranks=ranks,
            top_1=sum(rank==1 for rank in ranks.values()),
            top_3=sum(rank is not None and rank<=3 for rank in ranks.values()),
            top_5=sum(rank is not None for rank in ranks.values()))
    return report


def score_answers(questions,ask):
    """Compare one answer per question with what the set promised. Refusal means an empty answer."""
    rows=[]
    for q in questions:
        result=ask(q['query'])
        answer=result.get('answer') or ''
        expects_answer=q['kind']=='answerable' or q.get('expected_now')=='answerable'
        missing=missing_values(q,answer) if expects_answer else []
        if expects_answer:
            outcome='values_present' if answer and not missing else ('refused' if not answer else 'values_missing')
        else:
            outcome='refused' if not answer else 'answered_without_source'
        rows.append(dict(id=q['id'],kind=q['kind'],query=q['query'],outcome=outcome,missing_values=missing,
            answer=answer,message=result.get('message'),route=result.get('route'),reason=result.get('reason_code'),
            llm_calls=result.get('llm_calls'),answer_characters=len(answer)))
    def count(kind,outcome):
        return sum(r['kind']==kind and r['outcome']==outcome for r in rows)
    return dict(summary=dict(
        answerable_values_present=count('answerable','values_present'),answerable_values_missing=count('answerable','values_missing'),
        answerable_refused=count('answerable','refused'),unanswerable_refused=count('unanswerable','refused'),
        unanswerable_answered=count('unanswerable','answered_without_source'),reception_refused=count('reception','refused'),
        reception_answered_without_source=count('reception','answered_without_source'),reception_values_present=count('reception','values_present'),
        llm_calls=sum(r['llm_calls'] or 0 for r in rows)),rows=rows)


def export_review(data,path):
    """Write the plain page a person reads before locking."""
    lines=['# W04 шалгах асуултын ноорог','',
        f"**Төлөв:** {'түгжсэн' if data.get('status')=='locked' else 'ноорог, хүн хянаагүй'}. Агент сайтын эхээс бичсэн; систем эдгээр асуултыг хараахан хараагүй.",'',
        'Асуулт бүрийг холбоосоор нь шалгаж, буруу бол `data/rag-locked-questions-20261102.json`-д засна. Түгжсэний дараа өөрчлөхгүй.','',
        '## Хариутай 20','','| № | Асуулт | Зөв хариу | Эх |','|---|---|---|---|']
    for q in data['questions']:
        if q['kind']=='answerable':
            lines.append(f"| {q['id']} | {q['query']} | {q['answer_mn']} | [эх]({q['support'][0]['url']}) |")
    lines+=['','## Хариугүй 10 (систем "мэдээлэл алга" гэх ёстой)','','| № | Асуулт | Яагаад хариугүй |','|---|---|---|']
    for q in data['questions']:
        if q['kind']=='unanswerable':
            lines.append(f"| {q['id']} | {q['query']} | {q['why_mn']} |")
    lines+=['','## Ресепшний 10','','| № | Асуулт | Одоо | Сургуулийн мэдээлэл ирсний дараа |','|---|---|---|---|']
    for q in data['questions']:
        if q['kind']=='reception':
            now=q['answer_mn'] if q['expected_now']=='answerable' else 'Мэдээлэл алга гэх ёстой'
            lines.append(f"| {q['id']} | {q['query']} | {now} | {q['after_data_mn']} |")
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')


def run(data,output):
    """One-shot run through the real route with external network and LLM calls blocked."""
    require_locked(data)
    import os,socket,threading,http.client
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    sys.path.insert(0,str(ROOT))
    real_connect=socket.socket.connect
    def guarded(self,address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','localhost','::1'):
            raise OSError('network blocked by locked-set run')
        return real_connect(self,address)
    socket.socket.connect=guarded
    import llm_runtime
    def forbidden(*args,**kwargs):
        raise AssertionError('LLM request attempted')
    llm_runtime._http_json=forbidden
    from demo_server import make_server
    from website_retrieval import WebsiteRetriever
    retriever=WebsiteRetriever(root=ROOT)
    def search(query,mode):
        return retriever.search(query,limit=5,mode=mode)['candidates']
    server=make_server(port=0,project_root=ROOT)
    port=server.server_address[1]
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def ask(query):
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=120)
        connection.request('POST','/api/route',json.dumps(dict(query=query)).encode(),
            {'Content-Type':'application/json','Host':f'127.0.0.1:{port}'})
        body=json.loads(connection.getresponse().read())
        connection.close()
        return body
    try:
        report=dict(created_utc=datetime.now(timezone.utc).isoformat(),scope=SCOPE,
            questions_sha256=data['questions_sha256'],locked_by=data['locked_by'],retrieval=score_retrieval(data['questions'],search),
            answers=score_answers(data['questions'],ask),retrieval_status=retriever.status())
    finally:
        server.shutdown()
        server.server_close()
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8',newline='\n') as handle:
        json.dump(report,handle,ensure_ascii=False,indent=1)
    return report


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--set',type=Path,default=DEFAULT_SET)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--validate',action='store_true',help='check the set against stored pages; runs no answers')
    action.add_argument('--export-review',type=Path,help='write the page a person reads before locking')
    action.add_argument('--lock',metavar='NAME',help='a person names themselves after reviewing')
    action.add_argument('--run',type=Path,metavar='OUTPUT',help='one-shot scoring run; needs a locked set and .venv-modeltools')
    args=parser.parse_args()
    if args.lock:
        print(json.dumps({k:v for k,v in lock(args.set,args.lock).items() if k!='questions'},ensure_ascii=False))
        raise SystemExit(0)
    data=json.loads(args.set.read_text(encoding='utf-8'))
    if args.validate:
        problems=validate_shape(data)+validate_sources(data['questions'],stored_texts(ROOT/'CORE/database/website.db'))
        print(json.dumps(dict(status=data['status'],questions=len(data['questions']),problems=problems),ensure_ascii=False,indent=1))
        raise SystemExit(1 if problems else 0)
    if args.export_review:
        export_review(data,args.export_review)
        print(args.export_review)
    else:
        report=run(data,args.run)
        print(json.dumps(dict(retrieval={m:{k:r[k] for k in ('top_1','top_3','top_5')} for m,r in report['retrieval'].items()},
            answers=report['answers']['summary']),ensure_ascii=False))
