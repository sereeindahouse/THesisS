'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const topicLabels = {all:'Бүгд',admissions:'Элсэлт',programs:'Хөтөлбөр',olympiad:'Олимпиад',news:'Мэдээ',contact:'Холбоо',other:'Бусад'};
  const aliases = {'элсэлт':'admissions','хөтөлбөр':'programs','олимпиад':'olympiad','мэдээ':'news','холбоо':'contact','бусад':'other',admission:'admissions',program:'programs'};
  const state = {data:null,sources:[],filtered:[],topic:'all',kind:'all',query:'',selected:null,page:1,pageSize:8,view:'knowledge'};
  const views=['knowledge','tree','curated','progress'];
  const treeState={data:null,pending:false,selected:null,query:'',expanded:new Set()};
  const topicGraph={layout:null,controller:null,nodes:new Map(),edges:[],key:null};
  const brainGraph={layout:null,controller:null,nodes:new Map(),edges:[],key:null};
  let toastTimer;
  const norm = text => String(text || '').normalize('NFKC').toLocaleLowerCase('mn');
  const words = text => norm(text).match(/[\p{L}\p{N}]+/gu)||[];
  const matchesWords = (queryWords,indexedWords) => queryWords.every(query=>indexedWords.some(indexed=>indexed.startsWith(query)));
  const curatedWordCache = new WeakMap();
  const str = value => value == null ? '' : Array.isArray(value) ? value.join(' · ') : typeof value === 'object' ? JSON.stringify(value) : String(value);
  const factText = value => value && typeof value === 'object' && !Array.isArray(value) && 'published_clause' in value ? str(value.published_clause) : str(value);
  const number = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('mn-MN') : '—';
  const date = value => {
    if (!value) return 'Бүртгээгүй';
    const match = String(value).match(/^(\d{4})[-.](\d{2})[-.](\d{2})/);
    return match ? `${match[1]}.${match[2]}.${match[3]}` : String(value);
  };
  function element(tag, className, text) {const el=document.createElement(tag);if(className)el.className=className;if(text!=null)el.textContent=text;return el;}
  function highlighted(text, query) {
    const fragment = document.createDocumentFragment();
    const input = str(text), needle = query.trim();
    if (!needle) {fragment.append(document.createTextNode(input));return fragment;}
    // NFKC may change string length: search the displayed string so offsets stay correct.
    const lower = input.toLocaleLowerCase('mn'), target = needle.toLocaleLowerCase('mn');
    let offset=0,count=0,index;
    while ((index=lower.indexOf(target,offset))>=0 && count<200) {
      fragment.append(document.createTextNode(input.slice(offset,index)));
      fragment.append(element('mark','',input.slice(index,index+target.length)));
      offset=index+target.length;count++;
    }
    fragment.append(document.createTextNode(input.slice(offset)));return fragment;
  }
  function safeLink(value) {try{const url=new URL(String(value));return /^https?:$/.test(url.protocol)?url.href:null;}catch{return null;}}
  function prepareSources(sources) {
    return sources.map((item,index)=>{
      const source={...item,id:String(item.id??index),title:str(item.title||item.url||'Нэргүй эх'),text:str(item.text),url:str(item.url)};
      source.topic=aliases[norm(item.topic)]||item.topic||'other';
      if(!topicLabels[source.topic]) source.topic='other';
      source.kind=str(item.kind||'HTML').toUpperCase();
      source.search=norm([source.title,source.text,source.url,source.locator,source.version].join(' '));
      source.searchWords=Array.from(new Set(words(source.search)));
      return source;
    });
  }
  function renderStats() {
    const s=state.data.summary||{}, stats=$('stats');stats.replaceChildren();
    const values=[['HTML хуудас',s.pages,'Татаж хадгалсан эх','▤'],['Хайлтын хэсэг',s.indexed_passages,'RAG индексэд орсон текст','⌕'],['Эх баримт',s.documents,'Зураг болон PDF файл','▧'],['Түүхий текстийн хэсэг',s.raw_chunks,'HTML-ээс задалсан бүртгэл','≋']];
    values.forEach(([label,value,note,symbol])=>{const card=element('div','stat-card');card.append(element('div','stat-label',label),element('div','stat-number',number(value)),element('div','stat-footnote',note),element('span','stat-symbol',symbol));stats.append(card);});
    const snapshot=s.retrieved_at||s.snapshot_date||s.updated_at||s.generated_at;
    $('snapshotLabel').textContent=snapshot?`Хадгалсан эх · ${date(snapshot)}`:'Хадгалсан эхийн жагсаалт';
    if(s.scope_note){$('scopeNote').replaceChildren(element('span','', '↳'),document.createTextNode(str(s.scope_note)));}
    if(s.client_tab_passages){$('scopeNote').append(document.createTextNode(` Тэнхимийн нэмэлт табаас ${number(s.client_tab_passages)} заалт хайлтад орсон.`));}
    if(s.curated){$('scopeNote').append(document.createTextNode(` Бүтэцтэй сан: ${number(s.curated.sources)} эх / ${number(s.curated.facts)} баримт / ${number(s.curated.faqs)} FAQ.`));}
  }
  function renderTopics() {
    const row=$('topicFilters');row.replaceChildren();
    Object.entries(topicLabels).forEach(([id,label])=>{
      const count=id==='all'?state.sources.length:state.sources.filter(s=>s.topic===id).length;
      const chip=element('button',`topic-chip${state.topic===id?' active':''}`,label);chip.type='button';chip.dataset.topic=id;chip.setAttribute('aria-pressed',String(state.topic===id));chip.append(element('span','',count));chip.addEventListener('click',()=>{const focused=document.activeElement===chip;state.topic=id;state.page=1;applyFilters();if(focused)row.querySelector(`[data-topic="${id}"]`)?.focus();});row.append(chip);
    });
  }
  function applyFilters() {
    const queryWords=words(state.query);
    state.filtered=state.sources.filter(s=>(state.topic==='all'||s.topic===state.topic)&&(state.kind==='all'||(state.kind==='document'?Number(s.document_passages)>0||s.kind!=='HTML':s.kind===state.kind))&&matchesWords(queryWords,s.searchWords));
    const totalPages=Math.max(1,Math.ceil(state.filtered.length/state.pageSize));state.page=Math.min(Math.max(1,state.page),totalPages);
    const pageSources=state.filtered.slice((state.page-1)*state.pageSize,state.page*state.pageSize);
    if(!pageSources.some(s=>s.id===state.selected))state.selected=pageSources[0]?.id||null;
    $('resultCount').textContent=`${number(state.filtered.length)} эх · нийт ${number(state.sources.length)} бүртгэлээс${state.query.trim()?` · «${state.query.trim()}»`:''}`;
    $('clearFilters').hidden=state.topic==='all'&&state.kind==='all'&&!state.query.trim();
    $('emptyState').hidden=state.filtered.length>0;$('pagination').hidden=state.filtered.length<=state.pageSize;
    $('pageInfo').textContent=`${state.page} / ${totalPages}`;$('previousPage').disabled=state.page===1;$('nextPage').disabled=state.page===totalPages;
    renderTopics();renderList();renderDetail();
  }
  function renderList() {
    const list=$('sourceList');list.replaceChildren();
    const start=(state.page-1)*state.pageSize;
    state.filtered.slice(start,start+state.pageSize).forEach(source=>{
      const card=element('button',`source-card${source.id===state.selected?' selected':''}`);card.type='button';card.dataset.sourceId=source.id;card.setAttribute('aria-pressed',String(source.id===state.selected));card.setAttribute('aria-controls','sourceDetail');
      const top=element('div','source-card-top');top.append(element('span',`kind-badge ${source.kind.toLowerCase()}`,source.kind),element('span','source-topic',topicLabels[source.topic]));
      const title=element('span','source-card-title');title.append(highlighted(source.title,state.query));
      const preview=element('p','source-card-preview');preview.append(highlighted(source.text.replace(/\s+/g,' ').slice(0,180),state.query));
      const foot=element('div','source-card-footer');foot.append(element('span','',`${number(source.indexed_passages||0)} хайлтын хэсэг`),element('span','',date(source.retrieved_at)),element('span','','↗'));
      card.append(top,title,preview,foot);card.addEventListener('click',()=>{const focused=document.activeElement===card;state.selected=source.id;renderList();renderDetail();if(focused)Array.from(list.children).find(el=>el.dataset.sourceId===source.id)?.focus({preventScroll:true});if(matchMedia('(max-width:720px)').matches)$('sourceDetail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'start'});});list.append(card);
    });
  }
  function addMeta(grid,label,value) {const item=element('div');item.append(element('dt','',label),element('dd','',str(value)||'Бүртгээгүй'));grid.append(item);}
  function renderDetail() {
    const target=$('sourceDetail'),source=state.sources.find(s=>s.id===state.selected);target.replaceChildren();
    if(!source){const holder=element('div','detail-placeholder');holder.append(element('span','','▤'),element('p','','Хадгалсан эх сонгогдоогүй байна.'));target.append(holder);return;}
    const head=element('div','detail-header'),kicker=element('div','detail-kicker');kicker.append(element('span',`kind-badge ${source.kind.toLowerCase()}`,source.kind),element('span','',topicLabels[source.topic]));
    const title=element('h3','detail-title');title.append(highlighted(source.title,state.query));head.append(kicker,title);
    const href=safeLink(source.url);
    if(href){const link=element('a','official-link',`${new URL(href).hostname}${new URL(href).pathname} ↗`);link.href=href;link.target='_blank';link.rel='noopener noreferrer';link.setAttribute('aria-label','Албан эхийг шинэ цонхонд нээх');head.append(link);}else{head.append(element('p','official-link','Эхийн холбоос бүртгээгүй'));}
    const meta=element('dl','detail-metadata');
    addMeta(meta,'Хадгалсан огноо',date(source.retrieved_at));addMeta(meta,'Хувилбар / бүртгэл',source.version||source.id);
    addMeta(meta,'Хайлтын индекс',`${number(source.indexed_passages||0)} хэсэг`);addMeta(meta,'HTML / баримтын хэсэг',`${number(source.raw_chunks||0)} / ${number(source.document_passages||0)}`);
    if(source.client_tab_passages){addMeta(meta,'Нэмэлт табын заалт',number(source.client_tab_passages));addMeta(meta,'Нэмэлт таб хадгалсан',(source.client_tab_retrieved_at||[]).map(date).join(', '));}
    addMeta(meta,'Баримтын байрлал',source.locator||'HTML хуудасны текст');addMeta(meta,'Текст гаргасан арга',source.extraction_method||'Хадгалсан HTML текст');
    if(source.reviewer_kind)addMeta(meta,'Нягтлалтын бүртгэл',source.reviewer_kind);
    target.append(head,meta);
    if(Number(source.document_passages)>0||/assistant/i.test(str(source.reviewer_kind)+str(source.extraction_method)))target.append(element('p','detail-note','Баримтын сонгосон хэсгийг туслах буулгаж, эхтэй харьцуулсан. Энэ нь бүтэн OCR эсвэл сургуулийн ажилтны баталгаажуулалт биш.'));
    else if(source.kind!=='HTML')target.append(element('p','detail-note','Эх файл хадгалагдсан боловч энэ баримтаас сонгосон заалтын текст буулгаагүй. Эх файлыг нээж өөрөө шалгаж болно.'));
    const body=element('div','detail-body'),heading=element('div','text-heading');heading.append(element('h3','',source.kind==='HTML'?'Хадгалсан хуудасны текст':Number(source.document_passages)>0?'Сонгосон заалтын текст':'Текст буулгаагүй баримт'));
    const copy=element('button','copy-button','Хуулах');copy.type='button';copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(source.text);toast('Эхийн текстийг хууллаа.');}catch{toast('Хуулж чадсангүй. Доорх текстийг сонгож хуулж болно.');}});heading.append(copy);
    const text=element('pre','source-fulltext');text.tabIndex=0;text.setAttribute('aria-label','Хадгалсан эхийн бүтэн текст');text.append(highlighted(source.text||'Энэ бүртгэлд текст хадгалаагүй байна.',state.query));
    body.append(heading,text,element('p','text-caption','Энд хуудасны үндсэн текст, сонгосон нэмэлт таб болон баримтын заалтыг байрлалтай нь харуулна. Сайтын бүх таб, бүтэн OCR хамрагдсан гэж үзэхгүй. Татсан огнооны хувилбар тул шинэ өөрчлөлт автоматаар орсон гэсэн үг биш.'));
    if(source.preview_url&&/^\/api\/explorer\/document\/[a-zA-Z0-9_-]+$/.test(source.preview_url)){
      const link=element('a','capture-link','Хадгалсан эхийг нээх ↗');link.href=source.preview_url;link.target='_blank';link.rel='noopener noreferrer';body.append(link);
      if(source.kind==='PNG'){const preview=element('details','capture-preview');preview.append(element('summary','','Хадгалсан зургийг энд үзэх'));const image=element('img');image.src=source.preview_url;image.alt=`Хадгалсан эх зураг: ${source.title}`;image.loading='lazy';preview.append(image);body.append(preview);}
    }
    if(Array.isArray(source.passages)&&source.passages.length){const passages=element('details','passage-list');passages.append(element('summary','',`Сонгосон ${source.passages.length} заалтын байрлал`));source.passages.forEach(passage=>{const item=element('div','passage-item');item.append(element('strong','',str(passage.locator)||'Байрлал бүртгээгүй'),element('p','',str(passage.text)));if(passage.retrieved_at)item.append(element('small','',`Табыг хадгалсан: ${date(passage.retrieved_at)} · SHA256 ${str(passage.text_sha256).slice(0,12)}`));passages.append(item);});body.append(passages);}
    target.append(body);
  }
  function milestoneState(value) {const v=norm(value);if(['done','complete','completed','implemented','pass','finished','ready','дууссан'].includes(v))return 'done';if(['in_progress','in-progress','partial','active','ongoing','үргэлжилж буй'].includes(v))return 'in-progress';return 'planned';}
  function renderProgress() {
    const progress=state.data.progress||{},milestones=Array.isArray(progress.milestones)?progress.milestones:[],done=milestones.filter(m=>milestoneState(m.state)==='done').length;
    const summary=$('progressSummary');summary.replaceChildren();
    const counts=element('div','progress-count-card'),figure=element('div','progress-number',done);figure.append(element('small','',` / ${milestones.length}`));const description=element('div');description.append(element('h2','','Ажиллах хувилбарын дууссан шалгуур'),element('p','',progress.scope_label||'Доорх ажлын жагсаалтын төлөв. Дипломын нийт хувь гэж үзэхгүй.'));counts.append(figure,description);
    const calendar=element('div','progress-calendar');[['Идэвхтэй хүрээ',progress.current_week||'Явцын бүртгэлээс харна'],['Ажиллах хувилбарын зорилт',date(progress.target_date||'2026-11-10')],['Үнэлгээний төлөв',progress.evaluation_label||'Ерөнхий зөв хариултын хувь батлагдаагүй']].forEach(([label,value])=>{const row=element('div');row.append(element('span','',label),element('strong','',str(value)));calendar.append(row);});summary.append(counts,calendar);
    const latest=progress.latest_update;
    if(latest && Array.isArray(latest.items) && latest.items.some(item=>typeof item==='string' && item.trim())){
      const card=element('section','week-summary');card.style.gridColumn='1 / -1';card.style.marginBottom='0';
      card.append(element('h2','',`${latest.date?date(latest.date)+' — ':''}${str(latest.title)||'Сүүлд дууссан ажил'}`));
      const items=element('ul');latest.items.filter(item=>typeof item==='string' && item.trim()).forEach(item=>{const row=element('li');row.append(element('span','',item));items.append(row);});card.append(items);summary.append(card);
    }
    const list=$('milestones');list.replaceChildren();
    milestones.forEach((m,index)=>{const status=milestoneState(m.state),card=element('article',`milestone ${status}`),content=element('div');content.append(element('h3','',m.label||`Шалгуур ${index+1}`),element('p','',str(m.detail)));
      if(m.evidence){const evidence=element('div','milestone-evidence',`Нотолгоо · ${str(m.evidence)}`);content.append(evidence);}
      card.append(element('span','milestone-icon',status==='done'?'✓':status==='in-progress'?'◷':'○'),content,element('span','milestone-state',status==='done'?'Дууссан':status==='in-progress'?'Үргэлжилж буй':'Үлдсэн'));list.append(card);
    });
    if(!milestones.length)list.append(element('p','scope-note','Явцын шалгуур API-д хараахан бүртгэгдээгүй. CORE/ROADMAP-PROGRESS.mn.md-ээс бодит нотолгоог харна уу.'));
    const week=progress.week03,weekTarget=$('week03Summary');weekTarget.replaceChildren();weekTarget.hidden=!week;
    if(week){const title=element('h2','',week.complete?'3-р долоо хоногийн техникийн үе · дууссан':'3-р долоо хоногийн техникийн үе · үргэлжилж буй');weekTarget.append(title,element('p','',str(week.scope_label)));
      if(Array.isArray(week.criteria)){const details=element('details');details.append(element('summary','',`${week.criteria.filter(c=>milestoneState(c.state)==='done').length} / ${week.criteria.length} шалгуур · нотолгоог харах`));const ul=element('ul');week.criteria.forEach(c=>{const li=element('li');li.append(element('strong','',str(c.label)),element('span','',str(c.detail)));if(c.evidence)li.append(element('small','',`Нотолгоо: ${str(c.evidence)}`));ul.append(li);});details.append(ul);weekTarget.append(details);}
    }
    const research=Array.isArray(progress.research)?progress.research:[];$('researchSection').hidden=!research.length;const researchList=$('researchMilestones');researchList.replaceChildren();research.forEach(item=>{const status=milestoneState(item.state),row=element('article',`research-item ${status}`),content=element('div');content.append(element('h3','',str(item.label)),element('p','',str(item.detail)));row.append(content,element('span','milestone-state',status==='done'?'Дууссан':status==='in-progress'?'Үргэлжилж буй':'Үлдсэн'));researchList.append(row);});
    const limits=$('progressLimits');limits.replaceChildren();const messages=Array.isArray(progress.limitations)?progress.limitations:['Хөгжүүлэлтийн асуултуудын үр дүн нь хараат бус тестийн дүн биш.','Гуравдагч талын урьдчилан сурсан моделиудыг ашиглаж байна; өөрийн модель сургалт хийгээгүй.','Албан сайтаас татсан эх ашиглах зөвшөөрөл нь хүний хариултын чанарын үнэлгээг орлохгүй.'];messages.forEach(item=>limits.append(element('li','',str(item))));
  }
  function sourceRefs(refs,curated) {
    const holder=element('div','curated-refs');
    (Array.isArray(refs)?refs:[]).forEach(ref=>{const source=(curated.sources||[]).find(s=>s.document_id===ref.document_id&&(!ref.version||s.version===ref.version)),item=element('div','curated-ref'),title=source?.title||ref.document_id||'Эх бүртгэгдээгүй',href=safeLink(source?.source_url_or_filename);
      if(href){const link=element('a','',`${title} ↗`);link.href=href;link.target='_blank';link.rel='noopener noreferrer';item.append(link);}else item.append(element('strong','',title));
      item.append(element('small','',`${ref.document_id||''} · v${ref.version||'—'}${ref.locator?' · '+str(ref.locator):''}`));holder.append(item);
    });
    if(!holder.children.length)holder.append(element('span','curated-no-ref','Эхийн холбоос бүртгээгүй.'));return holder;
  }
  function scopeMetadata(item) {const meta=element('dl','curated-meta');addMeta(meta,'Хүрээ / нөхцөл',item.scope||'Бүртгээгүй');addMeta(meta,'Хүчинтэй хугацаа',`${item.valid_from?date(item.valid_from):'Эхлэх огноо заагаагүй'} → ${item.valid_until?date(item.valid_until):'Дуусах огноо заагаагүй'}`);addMeta(meta,'Анхны metadata',item.approval_status||'Бүртгээгүй');return meta;}
  function renderCurated() {
    const curated=state.data.curated||{},sources=Array.isArray(curated.sources)?curated.sources:[],facts=Array.isArray(curated.facts)?curated.facts:[],faqs=Array.isArray(curated.faqs)?curated.faqs:[],counts=$('curatedCounts');counts.replaceChildren();
    [['Бүртгэлтэй FAQ',faqs.length],['Бүтэцтэй баримт',facts.length],['Эхийн хувилбарын бүртгэл',sources.length]].forEach(([label,count])=>{const card=element('div','curated-count');card.append(element('strong','',number(count)),element('span','',label));counts.append(card);});
    $('curatedUnavailable').hidden=curated.available!==false;
    const query=norm($('curatedSearch').value).trim(),queryWords=words(query),matches=item=>{if(!curatedWordCache.has(item))curatedWordCache.set(item,Array.from(new Set(words(JSON.stringify(item)))));return matchesWords(queryWords,curatedWordCache.get(item));},shownFaqs=faqs.filter(matches),shownFacts=facts.filter(matches),shownSources=sources.filter(matches);
    $('curatedResultCount').textContent=`${shownFaqs.length} FAQ · ${shownFacts.length} баримт · ${shownSources.length} эх${query?' · хайлтад тохирсон':''}`;
    const faqList=$('faqList');faqList.replaceChildren();shownFaqs.forEach((faq,index)=>{const card=element('details','faq-card');if(index===0&&!query)card.open=true;const summary=element('summary'),heading=element('span','faq-heading');heading.append(element('small','',faq.faq_id),element('strong','',faq.question));summary.append(heading,element('span','faq-expand','+'));const body=element('div','faq-body');body.append(element('div','faq-answer',faq.answer||'Хариулт бүртгээгүй.'),scopeMetadata(faq));
      if(faq.answer_status)body.append(element('p','curated-answer-state',`Хариултын хүрээний төлөв: ${faq.answer_status}`));
      const aliases=Array.isArray(faq.question_aliases)?faq.question_aliases:[];body.append(element('h3','curated-small-title','Ижил асуултын бүртгэл'));const aliasList=element('div','alias-list');if(aliases.length)aliases.forEach(alias=>aliasList.append(element('span','',alias)));else aliasList.append(element('span','curated-no-ref','Нэмэлт хэллэг бүртгээгүй.'));body.append(aliasList);
      body.append(element('h3','curated-small-title','Холбосон баримт'));const linked=element('div','linked-facts');(faq.fact_ids||[]).forEach(id=>{const fact=facts.find(f=>f.fact_id===id),row=element('div','linked-fact');row.append(element('code','',id),element('span','',fact?factText(fact.value):'Баримтын бүртгэл олдсонгүй'));linked.append(row);});if(!linked.children.length)linked.append(element('span','curated-no-ref','Бүтэцтэй баримт холбогдоогүй.'));body.append(linked,element('h3','curated-small-title','Холбосон эх / байрлал'),sourceRefs(faq.source_refs,curated));card.append(summary,body);faqList.append(card);
    });if(!shownFaqs.length)faqList.append(element('p','curated-empty','Тохирох FAQ бүртгэл алга.'));
    const factsList=$('factsList');factsList.replaceChildren();shownFacts.forEach(fact=>{const card=element('article','fact-card');card.append(element('code','fact-id',fact.fact_id),element('h3','fact-value',factText(fact.value)),element('p','fact-key',`${fact.entity_id||'—'} · ${fact.key||'—'}`),scopeMetadata(fact),sourceRefs(fact.source_refs,curated));factsList.append(card);});if(!shownFacts.length)factsList.append(element('p','curated-empty','Тохирох баримт бүртгэл алга.'));
    const sourceList=$('curatedSourcesList');sourceList.replaceChildren();shownSources.forEach(source=>{const card=element('article','curated-source-card');card.append(element('h3','',source.title||source.document_id),element('code','',`${source.document_id} · v${source.version}`));const href=safeLink(source.source_url_or_filename);if(href){const link=element('a','official-link',`${source.source_url_or_filename} ↗`);link.href=href;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}card.append(element('p','curated-source-date',`Хадгалсан: ${date(source.retrieved_at)} · Capture: ${source.content_capture||'Бүртгээгүй'}`),scopeMetadata(source));sourceList.append(card);});if(!shownSources.length)sourceList.append(element('p','curated-empty','Тохирох эх бүртгэл алга.'));
  }
  function treeDescendants(topicId) {
    const selected=new Set([topicId]);let changed=true;
    while(changed){changed=false;treeState.data.topics.forEach(topic=>{if(selected.has(topic.parent_id)&&!selected.has(topic.topic_id)){selected.add(topic.topic_id);changed=true;}});}
    return treeState.data.topics.filter(topic=>selected.has(topic.topic_id));
  }
  function treeCounts(counts) {
    const holder=element('div','tree-count-chips');
    [['pages','хуудас'],['passages','хайлтын хэсэг'],['facts','баримт'],['faqs','FAQ']].forEach(([key,label])=>holder.append(element('span','',`${number(counts?.[key]||0)} ${label}`)));
    return holder;
  }
  // Native SVG diagrams. All topic nodes/edges come from the supplied taxonomy;
  // the second graph describes services, rather than learned neural weights.
  const SVG_NS='http://www.w3.org/2000/svg';
  const graphColours=[['#42735c','#eef5ee'],['#9a782e','#fbf5e7'],['#4f709b','#edf3fb'],['#39817b','#eaf6f2'],['#82649d','#f5eff9'],['#a56f45','#fbf1e9'],['#a36079','#fbf0f5'],['#477e91','#ecf5f8'],['#7b8581','#f1f4f1']];
  function svgElement(tag,attributes={},text) {const node=document.createElementNS(SVG_NS,tag);Object.entries(attributes).forEach(([key,value])=>node.setAttribute(key,String(value)));if(text!=null)node.textContent=text;return node;}
  function graphLabelLines(label,limit=19) {
    const lines=[];let line='';
    String(label).split(/\s+/).forEach(word=>{if(line&&(line+' '+word).length>limit){lines.push(line);line='';}while(word.length>limit){if(line){lines.push(line);line='';}lines.push(word.slice(0,limit));word=word.slice(limit);}line=line?line+' '+word:word;});if(line)lines.push(line);
    return lines;
  }
  function knowledgeGraphLayout(topics) {
    const byId=new Map(topics.map(topic=>[topic.topic_id,topic])),children=new Map(),roots=topics.filter(topic=>topic.parent_id===null);
    if(byId.size!==topics.length||roots.length!==1)throw new Error('Мод нэг үндэс, давхцахгүй сэдвүүдтэй байх шаардлагатай.');
    topics.forEach(topic=>{if(topic.parent_id!==null&&!byId.has(topic.parent_id))throw new Error('Модны эцэг сэдэв олдсонгүй.');if(!children.has(topic.parent_id))children.set(topic.parent_id,[]);children.get(topic.parent_id).push(topic);});
    const heights=new Map(),visited=new Set(),sizes=new Map(topics.map(topic=>[topic.topic_id,{lines:graphLabelLines(topic.label_mn),height:Math.max(80,graphLabelLines(topic.label_mn).length*24+32)}]));
    function measure(topic,ancestors=new Set()){if(ancestors.has(topic.topic_id))throw new Error('Модны холбоос тойрог үүсгэсэн байна.');visited.add(topic.topic_id);const next=new Set(ancestors).add(topic.topic_id),nested=children.get(topic.topic_id)||[];const height=Math.max(sizes.get(topic.topic_id).height,nested.reduce((sum,child)=>sum+measure(child,next),0)+Math.max(0,nested.length-1)*12);heights.set(topic.topic_id,height);return height;}
    const root=roots[0];measure(root);if(visited.size!==topics.length)throw new Error('Үндэстэй холбоогүй сэдэв байна.');
    const sides=[[],[]],totals=[0,0];(children.get(root.topic_id)||[]).forEach((topic,index)=>{const side=totals[0]<=totals[1]?0:1;sides[side].push({topic,index});totals[side]+=heights.get(topic.topic_id)+30;});
    const height=Math.max(...totals,300)+96,centreX=800,nodes=[],edges=[];
    const rootNode={id:root.topic_id,parent:null,x:centreX,y:height/2,width:270,height:96,label:root.label_mn,lines:graphLabelLines(root.label_mn),colour:'#285d50',fill:'#e7f1e8',root:true};nodes.push(rootNode);
    function place(topic,side,top,depth,colour,fill){const direction=side===0?-1:1,x=centreX+direction*(depth===1?350:660+(depth-2)*330),y=top+heights.get(topic.topic_id)/2,node={id:topic.topic_id,parent:topic.parent_id,x,y,width:depth===1?250:280,height:sizes.get(topic.topic_id).height,label:topic.label_mn,lines:sizes.get(topic.topic_id).lines,colour,fill,depth};nodes.push(node);edges.push({from:topic.parent_id,to:topic.topic_id,colour,horizontal:true});let nextTop=top;(children.get(topic.topic_id)||[]).forEach(child=>{place(child,side,nextTop,depth+1,colour,fill);nextTop+=heights.get(child.topic_id)+12;});}
    sides.forEach((groups,side)=>{let top=(height-(totals[side]||0)+30)/2;groups.forEach(({topic,index})=>{place(topic,side,top,1,...graphColours[index%graphColours.length]);top+=heights.get(topic.topic_id)+30;});});
    return {nodes,edges,width:1600,height,rootId:root.topic_id};
  }
  function graphEdgePath(edge,nodeMap) {
    if(edge.points)return edge.points.map((point,index)=>`${index?'L':'M'} ${point[0]} ${point[1]}`).join(' ');
    const from=nodeMap.get(edge.from),to=nodeMap.get(edge.to),dx=to.x-from.x,dy=to.y-from.y;
    let start,end;if(edge.horizontal||Math.abs(dx)>Math.abs(dy)*.65){const direction=dx>=0?1:-1;start={x:from.x+direction*from.width/2,y:from.y};end={x:to.x-direction*to.width/2,y:to.y};const middle=(start.x+end.x)/2;return `M ${start.x} ${start.y} C ${middle} ${start.y}, ${middle} ${end.y}, ${end.x} ${end.y}`;}
    const direction=dy>=0?1:-1;start={x:from.x,y:from.y+direction*from.height/2};end={x:to.x,y:to.y-direction*to.height/2};const middle=(start.y+end.y)/2;return `M ${start.x} ${start.y} C ${start.x} ${middle}, ${end.x} ${middle}, ${end.x} ${end.y}`;
  }
  function createGraphController(svg,scene,zoomLabel,layout) {
    const camera={x:0,y:0,scale:1,width:1000,height:760},points=new Map();let drag=null,pinch=null,suppressUntil=0;
    const listeners=[];
    function listen(type,handler,options){svg.addEventListener(type,handler,options);listeners.push([type,handler,options]);}
    function apply(){scene.setAttribute('transform',`translate(${camera.x} ${camera.y}) scale(${camera.scale})`);zoomLabel.value=`${Math.round(camera.scale*100)}%`;zoomLabel.textContent=zoomLabel.value;svg.dataset.graphScale=String(camera.scale);svg.dataset.graphX=String(camera.x);svg.dataset.graphY=String(camera.y);}
    function resize(){const bounds=svg.getBoundingClientRect();if(bounds.width>0&&bounds.height>0){camera.x+=(bounds.width-camera.width)/2;camera.y+=(bounds.height-camera.height)/2;camera.width=bounds.width;camera.height=bounds.height;}svg.setAttribute('viewBox',`0 0 ${camera.width} ${camera.height}`);apply();}
    function fit(ids){resize();const wanted=new Set(ids||layout.nodes.map(node=>node.id)),nodes=layout.nodes.filter(node=>wanted.has(node.id));if(!nodes.length)return;const left=Math.min(...nodes.map(node=>node.x-node.width/2)),right=Math.max(...nodes.map(node=>node.x+node.width/2)),top=Math.min(...nodes.map(node=>node.y-node.height/2)),bottom=Math.max(...nodes.map(node=>node.y+node.height/2));camera.scale=Math.max(.12,Math.min(1.8,(camera.width-48)/(right-left+24),(camera.height-48)/(bottom-top+24)));camera.x=camera.width/2-(left+right)/2*camera.scale;camera.y=camera.height/2-(top+bottom)/2*camera.scale;apply();}
    function zoom(factor,point={x:camera.width/2,y:camera.height/2}){const next=Math.max(.12,Math.min(3.5,camera.scale*factor)),ratio=next/camera.scale;camera.x=point.x-(point.x-camera.x)*ratio;camera.y=point.y-(point.y-camera.y)*ratio;camera.scale=next;apply();}
    function point(event){const bounds=svg.getBoundingClientRect();return {x:(event.clientX-bounds.left)*camera.width/(bounds.width||camera.width),y:(event.clientY-bounds.top)*camera.height/(bounds.height||camera.height)};}
    function pan(x,y){camera.x+=x;camera.y+=y;apply();}
    function ensureVisible(node){const x=node.x*camera.scale+camera.x,y=node.y*camera.scale+camera.y;if(x<40||x>camera.width-40||y<40||y>camera.height-40){camera.x=camera.width/2-node.x*camera.scale;camera.y=camera.height/2-node.y*camera.scale;apply();}}
    listen('wheel',event=>{event.preventDefault();zoom(Math.exp(-event.deltaY*.0014),point(event));},{passive:false});
    listen('pointerdown',event=>{if(event.button!==undefined&&event.button!==0)return;const p=point(event);points.set(event.pointerId,p);if(points.size===1)drag={id:event.pointerId,start:p,x:camera.x,y:camera.y};if(points.size===2){const [a,b]=[...points.values()],centre={x:(a.x+b.x)/2,y:(a.y+b.y)/2};pinch={distance:Math.hypot(a.x-b.x,a.y-b.y)||1,scale:camera.scale,world:{x:(centre.x-camera.x)/camera.scale,y:(centre.y-camera.y)/camera.scale}};for(const id of points.keys())svg.setPointerCapture?.(id);suppressUntil=Date.now()+200;drag=null;}});
    listen('pointermove',event=>{if(!points.has(event.pointerId))return;if(event.pointerType==='mouse'&&event.buttons===0){release(event);return;}const p=point(event);points.set(event.pointerId,p);if(points.size===2&&pinch){const [a,b]=[...points.values()],centre={x:(a.x+b.x)/2,y:(a.y+b.y)/2};camera.scale=Math.max(.12,Math.min(3.5,pinch.scale*Math.hypot(a.x-b.x,a.y-b.y)/pinch.distance));camera.x=centre.x-pinch.world.x*camera.scale;camera.y=centre.y-pinch.world.y*camera.scale;suppressUntil=Date.now()+200;apply();}else if(drag&&drag.id===event.pointerId){const dx=p.x-drag.start.x,dy=p.y-drag.start.y;if(Math.hypot(dx,dy)>4){svg.setPointerCapture?.(event.pointerId);suppressUntil=Date.now()+200;}camera.x=drag.x+dx;camera.y=drag.y+dy;apply();}});
    function release(event){if(svg.hasPointerCapture?.(event.pointerId))svg.releasePointerCapture?.(event.pointerId);points.delete(event.pointerId);pinch=null;drag=null;if(points.size===1){const [id,p]=[...points.entries()][0];drag={id,start:p,x:camera.x,y:camera.y};}}
    listen('pointerup',release);listen('pointercancel',release);
    listen('keydown',event=>{if(event.target!==svg)return;if(['+','=','-','0','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();if(['+','='].includes(event.key))zoom(1.25);else if(event.key==='-')zoom(.8);else if(event.key==='0')fit();else pan(event.key==='ArrowLeft'?50:event.key==='ArrowRight'?-50:0,event.key==='ArrowUp'?50:event.key==='ArrowDown'?-50:0);}});
    function dispose(){listeners.forEach(([type,handler,options])=>svg.removeEventListener(type,handler,options));listeners.length=0;points.clear();drag=null;pinch=null;}
    resize();return {fit,zoom,resize,pan,ensureVisible,dispose,suppressClick:()=>Date.now()<suppressUntil};
  }
  function drawSvgGraph(svg,graph,zoomLabel,layout,onSelect,{directed=false,title='',description=''}={}) {
    graph.controller?.dispose();
    svg.replaceChildren();const defs=svgElement('defs');if(directed){const marker=svgElement('marker',{id:'systemFlowArrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});marker.append(svgElement('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#8ba69a'}));defs.append(marker);}svg.append(defs,svgElement('title',{},title),svgElement('desc',{},description));
    const scene=svgElement('g',{'class':'graph-scene'}),lines=svgElement('g',{'class':'graph-edges'}),cards=svgElement('g',{'class':'graph-nodes'}),nodeMap=new Map(layout.nodes.map(node=>[node.id,node]));graph.nodes.clear();graph.edges=[];
    layout.edges.forEach(edge=>{const path=svgElement('path',{'class':'graph-edge','data-from':edge.from,'data-to':edge.to,d:graphEdgePath(edge,nodeMap),stroke:edge.colour||'#9db5a7',fill:'none','vector-effect':'non-scaling-stroke','stroke-linejoin':'round','stroke-linecap':'round'});if(edge.points)path.setAttribute('data-route-points',JSON.stringify(edge.points));if(directed)path.setAttribute('marker-end','url(#systemFlowArrow)');lines.append(path);graph.edges.push(path);});
    layout.nodes.forEach((node,index)=>{const group=svgElement('g',{'class':`graph-node${node.root?' graph-root':''}${node.llm?' graph-llm':''}`,'data-node-id':node.id,'data-parent-id':node.parent||'','data-x':node.x,'data-y':node.y,'data-width':node.width,'data-height':node.height,'data-colour':node.colour,'data-fill':node.fill,transform:`translate(${node.x-node.width/2} ${node.y-node.height/2})`,role:'button',tabindex:0,'aria-label':node.label,'aria-pressed':'false'});group.append(svgElement('title',{},node.label),svgElement('rect',{x:0,y:0,width:node.width,height:node.height,rx:node.root?24:17,fill:node.fill,stroke:node.colour,'stroke-width':1.5,'class':'graph-card'}));
      const dot=svgElement('circle',{cx:18,cy:19,r:4.5,fill:node.colour,'class':'graph-node-dot'});group.append(dot);const text=svgElement('text',{'class':'graph-node-label',x:32,y:node.lines.length===1?30:25,fill:'#24483d'});node.lines.forEach((line,lineIndex)=>text.append(svgElement('tspan',{x:32,dy:lineIndex===0?0:24},line)));group.append(text);const subtitle=svgElement('text',{'class':'graph-node-subtitle',x:18,y:node.height-12,fill:'#6e8677'},node.subtitle||'');group.append(subtitle);
      group.addEventListener('click',()=>{if(!graph.controller?.suppressClick())onSelect(node.id,true);});group.addEventListener('focus',()=>graph.controller?.ensureVisible(node));group.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();event.stopPropagation();onSelect(node.id,true);}else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();event.stopPropagation();const target=event.key==='ArrowLeft'?nodeMap.get(node.parent):event.key==='ArrowRight'?layout.nodes.find(other=>other.parent===node.id):layout.nodes[(index+(event.key==='ArrowUp'?-1:1)+layout.nodes.length)%layout.nodes.length];if(target)graph.nodes.get(target.id)?.focus();}});cards.append(group);graph.nodes.set(node.id,group);});scene.append(lines,cards);svg.append(scene);graph.layout=layout;graph.controller=createGraphController(svg,scene,zoomLabel,layout);graph.controller.fit();
  }
  function selectGraphTopic(identifier,focus=false) {
    const topic=treeState.data?.topics.find(item=>item.topic_id===identifier);if(!topic)return;treeState.selected=identifier;treeState.expanded.add(identifier);$('treeTopicJump').value=identifier;renderTopicTree();renderTreeDetail();if(focus)topicGraph.controller.fit(treeDescendants(identifier).map(item=>item.topic_id));
    if(matchMedia('(max-width:850px)').matches&&!treeState.data.topics.some(item=>item.parent_id===identifier))$('treeDetail').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth'});
  }
  function renderKnowledgeGraph(matches,visible) {
    if(!topicGraph.layout){const layout=knowledgeGraphLayout(treeState.data.topics);layout.nodes.forEach(node=>{const topic=treeState.data.topics.find(item=>item.topic_id===node.id),count=topic.subtree_counts||topic.direct_counts||{},refs=treeDescendants(node.id).reduce((sum,item)=>sum+(item.source_references||[]).length+(item.sources||[]).length,0);node.subtitle=count.passages?`${number(count.passages)} хэсэг · ${number(count.facts||0)} баримт`:refs?'Эхийн холбоос байна':`${number(count.facts||0)} баримт · ${number(count.faqs||0)} FAQ`;});drawSvgGraph($('knowledgeGraph'),topicGraph,$('treeZoomLabel'),layout,selectGraphTopic,{title:'Шинэ Монгол Коосэны мэдлэгийн мод',description:'Хадгалсан сургуулийн мэдээллийн сэдвүүд topic_contains холбоосоор салаална. Зангилааг сонгоод бодит эх, баримт, FAQ-г нээнэ.'});}
    const searching=Boolean(treeState.query.trim());topicGraph.nodes.forEach((group,id)=>{const node=topicGraph.layout.nodes.find(item=>item.id===id),selected=id===treeState.selected;group.setAttribute('class',`graph-node${node.root?' graph-root':''}${selected?' selected':''}${searching&&matches.has(id)?' search-match':''}${searching&&!visible.has(id)?' graph-muted':''}`);group.setAttribute('aria-pressed',String(selected));group.setAttribute('aria-controls','treeDetail');const topic=treeState.data.topics.find(item=>item.topic_id===id);group.setAttribute('aria-label',`${topic.label_mn}. ${node.subtitle}. Эхийг харах.`);});topicGraph.edges.forEach(edge=>edge.setAttribute('class',`graph-edge${searching&&(!visible.has(edge.getAttribute('data-from'))||!visible.has(edge.getAttribute('data-to')))?' graph-muted':''}`));
  }
  function renderSystemGraph() {
    if(brainGraph.layout)return;
    const definitions=[
      ['sources',90,90,'Албан эх','HTML · PDF · зураг','Албан nmct.edu.mn сайтаас хадгалсан HTML, сонгосон PDF/зураг, нэмэлт табын эх.'],
      ['database',420,90,'SQLite эхийн сан','URL · хувилбар · огноо','Хадгалсан хуудас болон бүтэцтэй fact/FAQ-г эх, хувилбар, хадгалсан огноотой нь хадгална.'],
      ['index',750,90,'Хайлтын хэсгүүд','Эхийн байрлал хадгална','HTML, баримт, нэмэлт табын текстийн хэсгүүдэд эхийн URL болон байрлал нь холбоотой байна.'],
      ['scope',1080,90,'Тодруулга / эхгүй','Хүрээг лавлана','Асуулт тодорхойгүй бол лавлана. Эх батлахгүй мэдээллийг өөр сэдвээр орлуулахгүй.'],
      ['microphone',90,370,'Микрофоны дуу','Хэрэглэгчийн асуулт','Хэрэглэгч дуугаар асуувал бичлэг STT рүү очно. Бичгээр асуух үед шууд асуултын текст рүү орно.'],
      ['stt',420,370,'Whisper STT','Cafet · урьдчилан сурсан','Урьдчилан сурсан Cafet Whisper Монгол яриаг текст болгоно. Анхны танилт хадгалагдана. Тусад нь тохируулсан локал Gemma текстийн засварын санал бэлтгэж болно; энэ нь Whisper-ийн жинг сургах эсвэл raw танилт сайжирсны баталгаа биш.'],
      ['query',750,370,'Асуултын текст','Бичсэн эсвэл таньсан','Анхны танилт шууд засах, илгээхэд бэлэн. Тохируулсан LLM-ийн саналыг хэрэглэгч сонгож хэрэглэвэл зассан асуулт илгээгдэнэ; анхны текст, бичлэгийн холбоо хадгалагдана. Бичсэн болон таньсан асуулт ижил чиглүүлэгч рүү орно.'],
      ['router',1080,370,'Асуулт чиглүүлэгч','Шууд · хайлт · тодруулга','Бүртгэлтэй хариултыг шууд өгөх, эх хайх, тодруулах эсвэл эхгүйг тайлбарлах замыг сонгоно.'],
      ['faq',1410,370,'Баримт / FAQ','Шууд хариултын зам','Тогтмол fact/FAQ хариулт нь өөрийн эх, хугацаа, нөхцөлийн шалгалттай. Энэ зам Gemma-г алгасаж болно.'],
      ['bm25',750,650,'BM25','Үгийн тохирол','Асуулттай үгээр тохирох эхийн хэсгүүдийг эрэмбэлнэ.'],
      ['e5',1080,650,'E5 embedding','Утгын ойролцоо хайлт','Урьдчилан сурсан multilingual E5 вектороор утгын ойролцоо хэсгүүдийг хайна.'],
      ['rrf',1410,650,'RRF нэгтгэл','Хоёр эрэмбийг нэгтгэнэ','BM25 болон E5-ийн эрэмбийг RRF нэгтгэж, эхийн нэр дэвшигч хэсгүүдийг бэлдэнэ.'],
      ['gemma',1410,930,'Gemma · локал LLM','Эхийн хэсгийн ID сонгоно','Энэ RAG замд Gemma асуулт, олдсон эхийг уншиж ашиглах хэсгийн ID-г сонгоно; сервер эхийн үгийг харуулна. STT бичвэрийн засварын санал нь тусдаа хүсэлт, тусдаа зориулалттай. Шууд fact/FAQ хариулт LLM-ийг алгасаж болно. Буруу сонголт хийх боломж үлдэнэ.'],
      ['guards',1080,930,'Эхийн шалгалтууд','ID · он · нөхцөл · талбар','Сервер сонгосон ID, эхийн холбоос, он, нөхцөл болон асуултад шаардсан талбарыг шалгана. Энэ нь бүх утгыг батлах төгс semantic шалгалт биш.'],
      ['answer',750,930,'Эхтэй хариулт','Эхийн текстийг үгчлэн','Сервер эхийн хадгалсан текст болон холбоосыг харуулна. Шууд FAQ зам өөрийн эхтэй хадгалсан хариултыг өгнө.'],
      ['tts',420,930,'Edge TTS','Хариулт → дуу','Дэлгэцэнд үзүүлсэн, тухайн хариултад холбосон текстийг Edge TTS дуу болгоно.']
    ];
    const nodes=definitions.map(([id,x,y,label,subtitle,detail])=>({id,x:x+70,y:y+35,width:270,height:96,label,subtitle,detail,lines:graphLabelLines(label),colour:id==='gemma'?'#98752e':['stt','e5','tts'].includes(id)?'#557fa4':'#4d7a65',fill:id==='gemma'?'#fcf1ce':['stt','e5','tts'].includes(id)?'#edf4fc':'#f1f7ef',llm:id==='gemma'}));
    const pairs=[['sources','database'],['database','index'],['database','faq'],['index','bm25'],['index','e5'],['microphone','stt'],['stt','query'],['query','router'],['router','scope'],['router','faq'],['router','bm25'],['router','e5'],['bm25','rrf'],['e5','rrf'],['rrf','gemma'],['gemma','guards'],['faq','guards'],['guards','answer'],['answer','tts']];
    // Explicit clear lanes keep long connections outside unrelated service
    // cards. Crossing a card would visually imply a connection that is absent.
    const routes={
      'database:faq':[[490,77],[490,28],[1480,28],[1480,357]],
      'index:bm25':[[955,125],[980,125],[980,594],[780,594],[780,637]],
      'index:e5':[[955,140],[998,140],[998,565],[1100,565],[1100,637]],
      'router:bm25':[[1100,453],[1100,520],[860,520],[860,637]],
      'router:e5':[[1210,453],[1210,637]],
      'bm25:rrf':[[820,733],[820,800],[1480,800],[1480,733]],
      'faq:guards':[[1615,405],[1645,405],[1645,860],[1150,860],[1150,917]]
    };
    const layout={nodes,edges:pairs.map(([from,to])=>({from,to,points:routes[from+':'+to]})),width:1680,height:1080};
    function select(identifier,focus=false){const node=nodes.find(item=>item.id===identifier);if(!node)return;brainGraph.nodes.forEach((group,id)=>{group.setAttribute('class',`graph-node${id==='gemma'?' graph-llm':''}${id===identifier?' selected':''}`);group.setAttribute('aria-pressed',String(id===identifier));});$('brainDetail').replaceChildren(element('h3','',node.label),element('p','',node.detail));if(focus)brainGraph.controller.ensureVisible(node);}
    drawSvgGraph($('systemGraph'),brainGraph,$('brainZoomLabel'),layout,select,{directed:true,title:'Системийн өгөгдөл боловсруулах холбоос',description:'Албан эхээс SQLite, BM25/E5, RRF, Gemma, эхийн шалгалт, хариулт болон TTS хүртэлх холбоос. Микрофоны дуу Whisper STT-ээр асуулт болно. Шууд FAQ зам Gemma-г алгасана.'});select('gemma');
  }
  function renderTreeDetail() {
    const topic=treeState.data.topics.find(item=>item.topic_id===treeState.selected),target=$('treeDetail');target.replaceChildren();if(!topic)return;
    const selected=treeDescendants(topic.topic_id),parent=treeState.data.topics.find(item=>item.topic_id===topic.parent_id);
    const heading=element('div','tree-detail-heading');heading.append(element('p','eyebrow muted',parent?.label_mn||'СУРГУУЛИЙН МЭДЭЭЛЛИЙН ҮНДЭС'),element('h2','',topic.label_mn),element('p','tree-detail-scope','Энэ салаа болон түүний дэд сэдвүүдийн хадгалсан бүртгэл.'),treeCounts(topic.subtree_counts||topic.direct_counts));target.append(heading);
    if(topic.parent_id===null){target.append(element('p','tree-detail-note','Модны сэдвийг сонгоход тухайн салааны эх, баримт, FAQ энд нээгдэнэ. Системийн урсгалын зургийг доороос харна уу.'));return;}
    const sources=[],seenSources=new Set();
    selected.forEach(node=>[...(node.sources||[]),...(node.source_references||[])].forEach(source=>{const href=safeLink(source.url);if(!href)return;const key=[href,source.version||''].join('|');if(seenSources.has(key))return;seenSources.add(key);sources.push({...source,url:href});}));
    const body=element('div','tree-detail-body');body.append(element('h3','',`Холбосон эхүүд · ${number(sources.length)}`));
    if(!sources.length)body.append(element('p','tree-gap','Энэ салаанд холбосон эхийн бүртгэл хараахан алга.'));
    const sourceList=element('ul','tree-source-list');sources.forEach(source=>{const item=element('li'),link=element('a','',`${source.title||source.literal_label||new URL(source.url).pathname||'Албан эх'} ↗`);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';item.append(link,element('small','',`${new URL(source.url).pathname}${source.version?' · хувилбар '+str(source.version):''}${source.retrieved_at?' · хадгалсан '+date(source.retrieved_at):''}`));if(source.literal_label)item.append(element('p','tree-source-context',`Эх дээрх сэдвийн тэмдэглэгээ: ${source.literal_label}`));const captured=state.sources.find(row=>safeLink(row.url)===source.url);if(captured){const open=element('button','text-button',captured.kind==='HTML'?'Одоогийн хадгалсан HTML текстийг нээх →':'Одоогийн хадгалсан эхийн текстийг нээх →');open.type='button';open.title='Энэ URL-ийн одоогийн хадгалсан эхийг нээнэ. HTML болон бүтэцтэй эхийн бүртгэлийн хувилбар тусдаа дугаарлагдаж болно.';if(captured.version!=null)item.append(element('small','tree-source-context',`Нээх хадгалсан эхийн өөрийн хувилбар: ${str(captured.version)}`));open.addEventListener('click',()=>{resetFilters();state.page=Math.floor(state.sources.findIndex(row=>row.id===captured.id)/state.pageSize)+1;applyFilters();state.selected=captured.id;renderList();renderDetail();setView('knowledge');$('sourceDetail').scrollIntoView({block:'start',behavior:'auto'});$('sourceDetail').tabIndex=-1;$('sourceDetail').focus({preventScroll:true});});item.append(open);}sourceList.append(item);});body.append(sourceList);
    const facts=selected.flatMap(node=>Array.isArray(node.fact_records)?node.fact_records:[]),faqs=selected.flatMap(node=>Array.isArray(node.faq_records)?node.faq_records:[]);
    if(!(topic.subtree_counts||topic.direct_counts)?.facts)body.append(element('p','tree-gap','Энэ салаанд тусдаа бүтэцтэй баримт бүртгэгдээгүй. Хуудасны эх хайлтад орсон байж болно.'));
    [['Бүтэцтэй баримтын бүртгэл',facts,'fact'],['Бүртгэлтэй FAQ',faqs,'faq']].forEach(([label,records,kind])=>{if(!records.length)return;const details=element('details','tree-records');details.append(element('summary','',`${label} · ${number(records.length)}`));const list=element('ul');records.forEach(record=>{const item=element('li');item.append(element('strong','',kind==='faq'?record.question:record.key||record.fact_id),element('p','',kind==='faq'?str(record.answer):factText(record.value)));list.append(item);});details.append(list);body.append(details);});
    body.append(element('p','tree-detail-note','Хуудас, хайлтын хэсэг, бүтэцтэй баримт, FAQ нь өөр өөр төрлийн бүртгэл. Нэг эх хэд хэдэн сэдэвтэй холбоотой байж болно.'));target.append(body);
  }
  function renderTopicTree() {
    const topics=treeState.data.topics,target=$('topicTree'),queryWords=words(treeState.query),matches=new Set();target.replaceChildren();
    topics.forEach(topic=>{const indexed=words([topic.label_mn,...(Array.isArray(topic.search_terms)?topic.search_terms:[]),...(topic.sources||[]).map(source=>source.title),...(topic.faq_records||[]).map(faq=>faq.question)].join(' '));if(matchesWords(queryWords,indexed))matches.add(topic.topic_id);});
    const visible=new Set(matches);topics.forEach(topic=>{if(!matches.has(topic.topic_id))return;let current=topic;const visited=new Set();while(current&&current.parent_id&&!visited.has(current.parent_id)){visited.add(current.parent_id);visible.add(current.parent_id);current=topics.find(item=>item.topic_id===current.parent_id);}});
    $('treeSearchStatus').textContent=treeState.query.trim()?`${number(matches.size)} сэдэв тохирлоо.`:'Тоонууд нь дэд сэдвүүдийг хамарсан хайлтын хэсэг, бүтэцтэй баримтын тоо.';
    function branch(parentId,ancestors=new Set()) {
      const list=element('ul','tree-branches');topics.filter(topic=>topic.parent_id===parentId&&visible.has(topic.topic_id)).forEach(topic=>{if(ancestors.has(topic.topic_id))return;const nextAncestors=new Set(ancestors).add(topic.topic_id),item=element('li'),row=element('div','tree-line'),children=topics.some(child=>child.parent_id===topic.topic_id&&visible.has(child.topic_id)),expanded=Boolean(treeState.query.trim())||treeState.expanded.has(topic.topic_id),childId=`treeChildren${topics.indexOf(topic)}`;
        if(children){const toggle=element('button','tree-toggle',expanded?'−':'+');toggle.type='button';toggle.disabled=Boolean(treeState.query.trim());toggle.setAttribute('aria-label',`${topic.label_mn} — ${expanded?'салааг хураах':'салааг нээх'}`);toggle.setAttribute('aria-expanded',String(expanded));toggle.setAttribute('aria-controls',childId);toggle.addEventListener('click',()=>{if(treeState.expanded.has(topic.topic_id))treeState.expanded.delete(topic.topic_id);else treeState.expanded.add(topic.topic_id);const index=topics.indexOf(topic);renderTopicTree();document.querySelector(`[data-tree-toggle="${index}"]`)?.focus();});toggle.dataset.treeToggle=topics.indexOf(topic);row.append(toggle);}else row.append(element('span','tree-leaf','·'));
        const button=element('button',`tree-topic${treeState.selected===topic.topic_id?' selected':''}`);button.type='button';button.dataset.treeTopic=topics.indexOf(topic);button.setAttribute('aria-pressed',String(treeState.selected===topic.topic_id));button.setAttribute('aria-controls','treeDetail');button.append(element('span','tree-topic-label',topic.label_mn),element('small','',`${number(topic.subtree_counts?.passages||0)} хэсэг · ${number(topic.subtree_counts?.facts||0)} баримт`));button.addEventListener('click',()=>{selectGraphTopic(topic.topic_id,true);document.querySelector(`[data-tree-topic="${topics.indexOf(topic)}"]`)?.focus({preventScroll:true});});row.append(button);item.append(row);if(children){const sublist=branch(topic.topic_id,nextAncestors);sublist.id=childId;sublist.hidden=!expanded;item.append(sublist);}list.append(item);});return list;
    }
    target.append(branch(null));if(!matches.size)target.append(element('p','tree-no-match','Тохирох сэдэв алга. Өөр нэрээр хайж үзээрэй.'));renderKnowledgeGraph(matches,visible);return {matches,visible};
  }
  function renderTree() {
    const data=treeState.data,totals=$('treeTotals');totals.replaceChildren();[['pages','HTML хуудас'],['passages','Хайлтын хэсэг'],['facts','Бүтэцтэй баримт'],['faqs','FAQ']].forEach(([key,label])=>{const card=element('div');card.append(element('strong','',number(data.counts?.[key]||0)),element('span','',label));totals.append(card);});
    $('treeTopicCount').textContent=`${number(data.topics.length)} сэдэв`;
    const jump=$('treeTopicJump');jump.replaceChildren(element('option','','Сэдэв сонгох…'));jump.children[0].value='';data.topics.forEach(topic=>{const option=element('option','',(topic.parent_id?'↳ ':'')+topic.label_mn);option.value=topic.topic_id;jump.append(option);});
    const release=data.release||{};$('treeRelease').textContent=release.release_id?`Идэвхтэй эхийн хувилбар: ${str(release.release_id)}`:'Идэвхтэй өгөгдлийн сангийн сэдвийн зураглал.';
    renderTopicTree();renderTreeDetail();renderSystemGraph();
  }
  async function loadTree() {
    if(treeState.data||treeState.pending)return;treeState.pending=true;$('treeLoadState').hidden=false;$('treeError').hidden=true;$('treeContent').hidden=true;
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
    try{const response=await fetch('/api/explorer/tree',{signal:controller.signal,headers:{Accept:'application/json'}});if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();if(data?.schema_version!==1||!Array.isArray(data.topics)||!data.topics.length||!data.topics.every(topic=>typeof topic.topic_id==='string'&&typeof topic.label_mn==='string'))throw new Error('Сэдвийн бүртгэлийн бүтэц тохирохгүй байна.');treeState.data=data;const root=data.topics.find(topic=>topic.parent_id===null);treeState.selected=root?.topic_id||data.topics[0].topic_id;treeState.expanded.add(treeState.selected);renderTree();$('treeContent').hidden=false;setTimeout(()=>{topicGraph.controller?.fit();brainGraph.controller?.fit();},0);}
    catch(error){treeState.data=null;treeState.selected=null;treeState.expanded.clear();[topicGraph,brainGraph].forEach(graph=>{graph.controller?.dispose();graph.controller=null;graph.layout=null;graph.nodes.clear();graph.edges=[];});$('treeError').hidden=false;$('treeErrorMessage').textContent=error.name==='AbortError'?'Мэдлэгийн модыг унших хугацаа хэтэрлээ. Дахин оролдоно уу.':`Мэдлэгийн модыг нээж чадсангүй. ${str(error.message)}`;}
    finally{clearTimeout(timer);treeState.pending=false;$('treeLoadState').hidden=true;}
  }
  function setView(view,focus=false) {if(!views.includes(view))view='knowledge';state.view=view;views.forEach(id=>{const active=id===view,button=$(id+'Tab');$(id+'View').hidden=!active;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});if(focus)$(view+'Tab').focus();if(state.data)history.replaceState(null,'',view==='knowledge'?'/data':`/data#${view}`);if(view==='tree')loadTree();}
  function resetFilters() {state.query='';state.topic='all';state.kind='all';state.page=1;$('sourceSearch').value='';$('kindFilter').value='all';applyFilters();}
  function toast(message) {$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3300);}
  async function load() {
    $('loadState').hidden=false;$('errorState').hidden=true;views.forEach(id=>$(id+'View').hidden=true);
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
    try{const response=await fetch('/api/explorer',{signal:controller.signal,headers:{Accept:'application/json'}});if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();if(!data||!Array.isArray(data.sources))throw new Error('API мэдээллийн бүтэц тохирохгүй байна.');state.data=data;state.sources=prepareSources(data.sources);renderStats();renderProgress();renderCurated();applyFilters();$('loadState').hidden=true;setView(views.includes(location.hash.slice(1))?location.hash.slice(1):state.view);}
    catch(error){$('loadState').hidden=true;$('errorState').hidden=false;$('errorMessage').textContent=error.name==='AbortError'?'Серверээс хариу ирэх хугацаа хэтэрлээ. Локал серверийг шалгаад дахин оролдоно уу.':'Локал мэдээллийн сангийн холболтыг шалгаад дахин оролдоно уу. '+str(error.message);}
    finally{clearTimeout(timer);}
  }
  views.forEach(id=>$(id+'Tab').addEventListener('click',()=>setView(id)));
  document.querySelector('.atlas-nav').addEventListener('keydown',event=>{if(['ArrowRight','ArrowLeft','ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const index=views.indexOf(state.view),next=event.key==='Home'?0:event.key==='End'?views.length-1:(index+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1)+views.length)%views.length;setView(views[next],true);}});
  $('treeSearch').addEventListener('input',event=>{treeState.query=event.target.value;if(treeState.data){const result=renderTopicTree();if(result.matches.size)topicGraph.controller.fit(treeState.query.trim()?[...result.matches]:undefined);}});$('retryTree').addEventListener('click',loadTree);
  $('treeSearch').addEventListener('keydown',event=>{if(event.key==='Escape'){event.target.value='';treeState.query='';if(treeState.data){renderTopicTree();topicGraph.controller.fit();}}});
  $('treeTopicJump').addEventListener('change',event=>{if(event.target.value)selectGraphTopic(event.target.value,true);});
  $('treeZoomIn').addEventListener('click',()=>topicGraph.controller?.zoom(1.25));$('treeZoomOut').addEventListener('click',()=>topicGraph.controller?.zoom(.8));$('treeFit').addEventListener('click',()=>topicGraph.controller?.fit());$('treeFocus').addEventListener('click',()=>{if(treeState.data)topicGraph.controller.fit(treeDescendants(treeState.selected).map(topic=>topic.topic_id));});
  $('treeReset').addEventListener('click',()=>{if(!treeState.data)return;treeState.query='';$('treeSearch').value='';treeState.selected=treeState.data.topics.find(topic=>topic.parent_id===null).topic_id;$('treeTopicJump').value=treeState.selected;renderTopicTree();renderTreeDetail();topicGraph.controller.fit();});
  $('brainZoomIn').addEventListener('click',()=>brainGraph.controller?.zoom(1.25));$('brainZoomOut').addEventListener('click',()=>brainGraph.controller?.zoom(.8));$('brainFit').addEventListener('click',()=>brainGraph.controller?.fit());
  let graphResizeTimer;window.addEventListener('resize',()=>{clearTimeout(graphResizeTimer);graphResizeTimer=setTimeout(()=>{if(state.view==='tree'){topicGraph.controller?.resize();brainGraph.controller?.resize();}},120);});
  $('curatedSearch').addEventListener('input',renderCurated);
  $('sourceSearch').addEventListener('input',event=>{state.query=event.target.value;state.page=1;applyFilters();});
  $('sourceSearch').addEventListener('keydown',event=>{if(event.key==='Escape'){event.target.value='';state.query='';state.page=1;applyFilters();}});
  $('kindFilter').addEventListener('change',event=>{state.kind=event.target.value;state.page=1;applyFilters();});
  $('clearFilters').addEventListener('click',resetFilters);$('emptyReset').addEventListener('click',resetFilters);$('retryLoad').addEventListener('click',load);
  $('previousPage').addEventListener('click',()=>{state.page--;applyFilters();});$('nextPage').addEventListener('click',()=>{state.page++;applyFilters();});
  window.addEventListener('hashchange',()=>{if(state.data)setView(views.includes(location.hash.slice(1))?location.hash.slice(1):'knowledge');});load();
})();
