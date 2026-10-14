'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const topicLabels = {all:'Бүгд',admissions:'Элсэлт',programs:'Хөтөлбөр',olympiad:'Олимпиад',news:'Мэдээ',contact:'Холбоо',other:'Бусад'};
  const aliases = {'элсэлт':'admissions','хөтөлбөр':'programs','олимпиад':'olympiad','мэдээ':'news','холбоо':'contact','бусад':'other',admission:'admissions',program:'programs'};
  const state = {data:null,sources:[],filtered:[],topic:'all',kind:'all',query:'',selected:null,page:1,pageSize:8,view:'knowledge'};
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
  function setView(view,focus=false) {state.view=view;['knowledge','curated','progress'].forEach(id=>{const active=id===view,button=$(id+'Tab');$(id+'View').hidden=!active;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});if(focus)$(view+'Tab').focus();if(state.data)history.replaceState(null,'',view==='knowledge'?'/data':`/data#${view}`);}
  function resetFilters() {state.query='';state.topic='all';state.kind='all';state.page=1;$('sourceSearch').value='';$('kindFilter').value='all';applyFilters();}
  function toast(message) {$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3300);}
  async function load() {
    $('loadState').hidden=false;$('errorState').hidden=true;$('knowledgeView').hidden=true;$('curatedView').hidden=true;$('progressView').hidden=true;
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
    try{const response=await fetch('/api/explorer',{signal:controller.signal,headers:{Accept:'application/json'}});if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();if(!data||!Array.isArray(data.sources))throw new Error('API мэдээллийн бүтэц тохирохгүй байна.');state.data=data;state.sources=prepareSources(data.sources);renderStats();renderProgress();renderCurated();applyFilters();$('loadState').hidden=true;setView(['#progress','#curated'].includes(location.hash)?location.hash.slice(1):state.view);}
    catch(error){$('loadState').hidden=true;$('errorState').hidden=false;$('errorMessage').textContent=error.name==='AbortError'?'Серверээс хариу ирэх хугацаа хэтэрлээ. Локал серверийг шалгаад дахин оролдоно уу.':'Локал мэдээллийн сангийн холболтыг шалгаад дахин оролдоно уу. '+str(error.message);}
    finally{clearTimeout(timer);}
  }
  ['knowledge','curated','progress'].forEach(id=>$(id+'Tab').addEventListener('click',()=>setView(id)));
  document.querySelector('.atlas-nav').addEventListener('keydown',event=>{if(['ArrowRight','ArrowLeft','ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const tabs=['knowledge','curated','progress'],index=tabs.indexOf(state.view),next=event.key==='Home'?0:event.key==='End'?2:(index+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1)+3)%3;setView(tabs[next],true);}});
  $('curatedSearch').addEventListener('input',renderCurated);
  $('sourceSearch').addEventListener('input',event=>{state.query=event.target.value;state.page=1;applyFilters();});
  $('sourceSearch').addEventListener('keydown',event=>{if(event.key==='Escape'){event.target.value='';state.query='';state.page=1;applyFilters();}});
  $('kindFilter').addEventListener('change',event=>{state.kind=event.target.value;state.page=1;applyFilters();});
  $('clearFilters').addEventListener('click',resetFilters);$('emptyReset').addEventListener('click',resetFilters);$('retryLoad').addEventListener('click',load);
  $('previousPage').addEventListener('click',()=>{state.page--;applyFilters();});$('nextPage').addEventListener('click',()=>{state.page++;applyFilters();});
  window.addEventListener('hashchange',()=>{if(state.data)setView(['#progress','#curated'].includes(location.hash)?location.hash.slice(1):'knowledge');});load();
})();
