"""Read-only catalogue of captured official sources and documented milestones.

Opening the catalogue never transcribes audio, loads E5, calls an LLM or changes
the content databases. Document previews must match captured bytes and paths.
"""
from collections import Counter
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from CORE.website_corpus import readonly
from CORE.document_corpus import official
from sqlite_retrieval import ReadOnlyContentStore
from website_retrieval import WebsiteRetriever


def source_id(kind, url, version=1):
    return kind+'-'+hashlib.sha256(f'{url}|{version}'.encode()).hexdigest()[:20]


def topic(url, title):
    path=urlsplit(url).path.casefold()
    text=title.casefold()
    if '/olympiad' in path or 'олимпиад' in text:
        return 'olympiad'
    if '/elsel' in path or 'элсэлт' in text:
        return 'admissions'
    if '/course' in path or '/program' in path or 'мэргэжил' in text or 'хөтөлбөр' in text:
        return 'programs'
    if '/contact' in path or 'холбоо барих' in text:
        return 'contact'
    if '/news' in path or 'мэдээ' in text:
        return 'news'
    return 'other'


def progress(root):
    path=root/'config/project-progress.json'
    if not path.is_file():
        return dict(scope_label='Үе шатны бүртгэл энэ хувилбарт байхгүй.',
                    milestones=[],completed=0,total=0,limitations=[])
    if path.stat().st_size>262144:
        raise ValueError('Progress manifest too large.')
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('schema_version')!=1:
        raise ValueError('Unsupported progress schema.')
    milestones=data['milestones']
    if (not isinstance(milestones,list) or len(milestones)>30
            or any(m.get('state') not in {'done','in_progress','todo'} for m in milestones)
            or len({m['id'] for m in milestones})!=len(milestones)):
        raise ValueError('Invalid milestone states/IDs.')
    # Do not trust an independently entered percentage/total.
    data.update(completed=sum(m['state']=='done' for m in milestones),total=len(milestones))
    return data


class SourceExplorer:
    def __init__(self,root,database=None,content_database=None):
        self.root=Path(root).resolve()
        self.database=Path(database or self.root/'CORE/database/website.db').resolve()
        self.content_database=Path(content_database or self.root/'runtime/content.db').resolve()

    def knowledge_tree(self):
        """Public navigation projection of this request's selected database pair.

        The CLI export deliberately retains private provenance. Never serve it
        directly: this view explicitly selects public fields and official URLs.
        It neither searches nor changes the answer-selection pipeline.
        """
        from tools.build_knowledge_tree import build_tree, load_inputs

        path=self.root/'config/knowledge-topics.json'
        if path.stat().st_size>65536:
            raise ValueError('Topic configuration too large.')
        config=json.loads(path.read_text(encoding='utf-8-sig'))
        tree=build_tree(config,load_inputs(self.root,website_database=self.database,
                                         content_database=self.content_database))
        records={record['content_id']:record for rows in tree['records'].values() for record in rows}
        public=[]
        for node in tree['topics']:
            links={}
            for group in ('pages','passages','sources'):
                for identifier in node['primary_record_ids'][group]:
                    payload=records[identifier]['payload']
                    url=payload.get('url') or payload.get('source_url_or_filename')
                    if not isinstance(url,str) or not official(url):
                        continue
                    key=(url,payload.get('version'))
                    if key not in links:
                        links[key]={k:payload.get(k) for k in ('title','version','retrieved_at','approval_status')}
                        links[key].update(url=url,kind=Path(urlsplit(url).path).suffix.casefold().lstrip('.') or 'html')
            references=[]
            for reference in node['source_references']:
                source=reference['source']
                if official(source['url']):
                    references.append({**{k:source.get(k) for k in ('url','version','retrieved_at')},
                                       'title':reference['literal_label'],'literal_label':reference['literal_label']})
            facts=[{k:v for k,v in records[identifier]['payload'].items()
                    if k in {'fact_id','entity_id','key','value','approval_status','valid_from','valid_until'}}
                   for identifier in node['primary_record_ids']['facts']]
            faqs=[{k:v for k,v in records[identifier]['payload'].items()
                   if k in {'faq_id','question','answer','answer_status','approval_status','valid_from','valid_until'}}
                  for identifier in node['primary_record_ids']['faqs']]
            public.append({**{k:node[k] for k in ('topic_id','parent_id','label_mn','direct_counts','subtree_counts')},
                           'search_terms':['багш','багш нар'] if node['topic_id'].startswith('academics.') and node['topic_id']!='academics.programs' else [],
                           'sources':list(links.values()),'source_references':references,
                           'fact_records':facts,'faq_records':faqs})
        return dict(schema_version=1,relation='topic_contains',counts=tree['counts'],topics=public,
                    taxonomy_sha256=tree['taxonomy_sha256'],readonly=True,llm_calls=0,
                    affects_retrieval=False,membership_establishes_answer_truth=False,
                    gaps={k:tree[k] for k in ('missing_source_topics','missing_fact_topics')},
                    limitations=['Сэдвийн ангиллыг хөгжүүлэгч санал болгосон; сургуулийн баталсан ангилал биш.',
                        'Эхтэй салбар нь бүрэн эсвэл өнөөдөр хүчинтэй мэдээлэлтэй гэсэн үг биш.',
                        'Fact/FAQ нь одоо хадгалсан бүртгэл; сэдэв бүрт баталсан хариулт байгаа гэсэн үг биш.',
                        'Мод нь эхийн навигац; одоогийн хайлтын эрэмбэ, Gemma-ийн сонголтыг өөрчлөхгүй.'])

    def snapshot(self):
        summary=dict(available=False,pages=0,raw_chunks=0,documents=0,
                     indexed_passages=0,indexed_html_passages=0,document_passages=0,client_tab_passages=0,
                     readonly=True,curated=dict(sources=0,facts=0,faqs=0),
                     corpus_id=None,retrieved_at=None)
        curated=dict(available=False,counts=dict(summary['curated']),sources=[],facts=[],faqs=[])
        try:
            with ReadOnlyContentStore(self.content_database) as store:
                counts=store.counts()
                summary['curated']={name:counts.get(name,0) for name in ('sources','facts','faqs')}
                package=store.export()
                common={'approval_status','valid_from','valid_until','scope'}
                fields={'sources':{'document_id','version','title','source_url_or_filename','retrieved_at','source_updated_at','content_capture'},
                        'facts':{'fact_id','entity_id','key','value','source_refs'},
                        'faqs':{'faq_id','question','answer','question_aliases','fact_ids','source_refs','answer_status'}}
                curated.update(available=True,counts=summary['curated'],
                    **{group:[{key:value for key,value in row.items() if key in keys|common}
                               for row in package[group]] for group,keys in fields.items()})
        except (OSError,sqlite3.Error,ValueError,KeyError):
            pass
        result=dict(summary=summary,sources=[],curated=curated,progress=progress(self.root),
            limitations=['Албан сайтын хадгалсан snapshot; өнөөдрийн төлөвийг батлахгүй.',
                'HTML-ийн хадгалсан текст ба PDF/зургийн сонгосон буулгалт; бүтэн OCR/client tab хамрагдаагүй.',
                'Баримтын буулгалтын assistant тэмдэглэгээ нь сургуулийн ажилтны баталгаа биш.',
                'Хайлтын үзүүлэлт ба автомат тест нь хариултын нийт зөв байдлын хувь биш.'])
        if not self.database.is_file():
            summary['message']='Локал веб эхийн сан олдсонгүй. Энэ дэлгэц мэдээлэл зохиож харуулахгүй.'
            summary['scope_note']=summary['message']
            return result
        retriever=WebsiteRetriever(self.root,self.database,use_dense=False)
        state=retriever.status()
        with retriever._lock:
            indexed=deepcopy(retriever._rows)
            indexed_run=deepcopy(retriever._run)
        index_counts=Counter(row['url'] for row in indexed)
        with closing(readonly(self.database)) as db:
            db.execute('BEGIN')
            run=db.execute('SELECT * FROM crawl_runs ORDER BY retrieved_at DESC,run_id DESC LIMIT 1').fetchone()
            if run is None:
                summary['message']='Веб эхийн capture run хараахан байхгүй.'
                return result
            if not indexed_run or run['run_id']!=indexed_run['run_id']:
                raise ValueError('Capture changed while reading the catalogue; try again.')
            pages=db.execute('SELECT p.* FROM pages p JOIN captures c ON p.url=c.url AND p.version=c.version '
                'WHERE c.run_id=? ORDER BY p.url',(run['run_id'],)).fetchall()
            chunks=Counter({row['url']:row['n'] for row in db.execute(
                'SELECT x.url,COUNT(*) n FROM chunks x JOIN captures c ON x.url=c.url AND x.version=c.version '
                'WHERE c.run_id=? GROUP BY x.url',(run['run_id'],))})
            assets=db.execute('SELECT * FROM assets WHERE run_id=? ORDER BY url',(run['run_id'],)).fetchall()
            for page in pages:
                url=page['url']
                if not official(url):
                    continue
                # Keep the main text and selected public client fields distinct.
                client=[row for row in indexed if row['url']==url and row.get('text_scope')=='client_tab_field_excerpt']
                extra=''.join('\n\n'+row['source_locator']+'\n'+row['text'] for row in client)
                # Ineligible pages remain inspectable, clearly separate from RAG.
                result['sources'].append(dict(id=source_id('html',url,page['version']),kind='html',
                    title=page['title'],url=url,text=page['text']+extra,topic=topic(url,page['title']),
                    version=page['version'],retrieved_at=page['retrieved_at'],
                    source_updated_at=page['source_updated_at'],locator='',text_scope=page['text_scope'],
                    extraction_method='html_text',reviewer_kind=None,
                    indexed_passages=index_counts[url],raw_chunks=chunks[url],document_passages=0,client_tab_passages=len(client),
                    client_tab_retrieved_at=sorted({row['retrieved_at'] for row in client}),
                    passages=[dict(locator=row['source_locator'],text=row['text'],retrieved_at=row['retrieved_at'],
                        text_sha256=hashlib.sha256(row['text'].encode()).hexdigest(),
                        html_sha256=row.get('html_sha256'),field_sha256=row.get('field_sha256')) for row in client],
                    content_sha256=page['text_sha256'],main_text_sha256=page['text_sha256'],
                    display_text_sha256=hashlib.sha256((page['text']+extra).encode()).hexdigest(),preview_url=None,
                    coverage='captured_html_with_selected_client_fields' if client else 'captured_html_text',approval_status=page['approval_status']))
            for asset in assets:
                url=asset['url']
                if not official(url):
                    continue
                kind=Path(urlsplit(url).path).suffix.casefold().lstrip('.')
                if kind not in {'png','pdf'}:
                    continue
                passages=[row for row in indexed if row['url']==url]
                version=max((row['version'] for row in passages),default=1)
                identifier=source_id(kind,url,asset['sha256'])
                titles=[row['title'].split(' — ')[0] for row in passages]
                title=titles[0] if titles else Path(urlsplit(url).path).name
                result['sources'].append(dict(id=identifier,kind=kind,title=title,url=url,
                    text='\n\n'.join(row.get('source_locator','')+'\n'+row['text'] for row in passages),
                    topic=topic(url,title),version=version,retrieved_at=passages[0]['retrieved_at'] if passages else run['retrieved_at'],
                    source_updated_at=None,locator='; '.join(row.get('source_locator','') for row in passages),
                    text_scope='document_visual_excerpt',extraction_method='visual_transcription' if passages else None,
                    reviewer_kind=passages[0].get('reviewer_kind') if passages else None,
                    indexed_passages=len(passages),document_passages=len(passages),raw_chunks=0,
                    content_sha256=asset['sha256'],preview_url='/api/explorer/document/'+identifier,
                    coverage='selected_passages' if passages else 'binary_only',
                    passages=[dict(locator=row.get('source_locator',''),text=row['text']) for row in passages]))
            summary.update(available=True,pages=sum(s['kind']=='html' for s in result['sources']),
                documents=sum(s['kind']!='html' for s in result['sources']),
                raw_chunks=sum(s['raw_chunks'] for s in result['sources']),indexed_passages=len(indexed),
                indexed_html_passages=sum(row.get('text_scope') not in {'document_visual_excerpt','client_tab_field_excerpt'} for row in indexed),
                document_passages=sum(row.get('text_scope')=='document_visual_excerpt' for row in indexed),
                client_tab_passages=sum(row.get('text_scope')=='client_tab_field_excerpt' for row in indexed),
                retrieved_at=run['retrieved_at'],corpus_id=state.get('corpus_id'),run_id=run['run_id'])
        return result

    def document(self,identifier):
        # Only a generated catalogue ID can select a captured PNG/PDF.
        with closing(readonly(self.database)) as db:
            run=db.execute('SELECT * FROM crawl_runs ORDER BY retrieved_at DESC,run_id DESC LIMIT 1').fetchone()
            if run is None:
                raise FileNotFoundError('No capture run.')
            for asset in db.execute('SELECT * FROM assets WHERE run_id=?',(run['run_id'],)):
                if not official(asset['url']):
                    continue
                kind=Path(urlsplit(asset['url']).path).suffix.casefold().lstrip('.')
                if kind not in {'png','pdf'}:
                    continue
                if source_id(kind,asset['url'],asset['sha256'])!=identifier:
                    continue
                snapshot=Path(run['snapshot_dir']).resolve()
                path=Path(asset['path']).resolve()
                if not snapshot.is_relative_to(self.root) or not path.is_relative_to(snapshot):
                    raise ValueError('Captured document path outside project snapshot.')
                if path.stat().st_size>8*1024*1024:
                    raise ValueError('Captured document exceeds preview size limit.')
                data=path.read_bytes()
                if hashlib.sha256(data).hexdigest()!=asset['sha256']:
                    raise ValueError('Captured document hash mismatch.')
                if kind=='png' and data.startswith(b'\x89PNG\r\n\x1a\n'):
                    return data,'image/png'
                if kind=='pdf' and data.startswith(b'%PDF-'):
                    return data,'application/pdf'
                raise ValueError('Captured document format mismatch.')
        raise FileNotFoundError('Unknown captured document ID.')
