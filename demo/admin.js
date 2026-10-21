/* Local operator view. Dynamic content is rendered as text, never as HTML. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {data: null, token: null, expected: null, selected: null, busy: false,
    stale: false, imported: null, content: null, contentSupported: true};
  const metricNames = {sources: 'Эх', facts: 'Баримт', faqs: 'FAQ', pages: 'Вэб хуудас',
    captures: 'Хадгалсан эх', chunks: 'Эхийн хэсэг', indexed_chunks: 'Хайлтын хэсэг', indexed_passages: 'Хайлтын хэсэг',
    passages: 'Хайлтын хэсэг', html_passages: 'Вэбийн хэсэг', assets: 'Баримт, зураг', documents: 'Баримт',
    document_passages: 'Баримтын хэсэг', client_passages: 'Нэмэлт хэсэг'};
  const groupNames = {sources: 'Эхийн бүртгэл', facts: 'Баримтууд', faqs: 'Асуулт, хариултууд', website_urls: 'Вэб эхүүд'};
  const selected = () => (state.data?.releases || []).find(row => row.release_id === state.selected);
  const activeId = () => state.data?.active_release_id || state.data?.active?.release_id || null;
  const activation = data => data?.active?.activation_token ?? data?.activation_token ?? null;
  const published = row => Boolean(row?.was_published || row?.activated_before || row?.published_utc || row?.first_published_utc || row?.release_id === activeId());
  const validated = row => row?.status === 'validated' || row?.state === 'validated';
  const locked = row => Boolean(row?.sealed || validated(row));
  const setText = (id, value) => { $(id).textContent = value ?? ''; };
  const element = (tag, text, className) => {const node = document.createElement(tag); node.textContent = text ?? ''; if (className) node.className = className; return node;};
  const show = (id, value = true) => { $(id).hidden = !value; };
  const dateLabel = value => {const date = new Date(value); return Number.isNaN(date.valueOf()) ? '' : date.toLocaleString('mn-MN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});};
  function message(text, error = false) {show(error ? 'notice' : 'errorNotice', false); setText(error ? 'errorNotice' : 'notice', text); show(error ? 'errorNotice' : 'notice');}
  function errorText(response, body) {
    if (response.status === 409) {state.stale = true; return 'Хувилбар эсвэл ноорог өөрчлөгдсөн байна. Төлөвийг дахин уншаад шалгаарай.';}
    if (response.status === 403) return 'Энэ үйлдэл зөвхөн локал админ хуудсаас ажиллана. Хуудсыг дахин ачаалж оролдоорой.';
    if (response.status === 413) return 'Оруулсан файл хэт том байна. Эхийн багцын хэмжээг багасгаж дахин оролдоорой.';
    const detail = body?.message || body?.error || body?.detail;
    return typeof detail === 'string' ? `Үйлдэл амжилтгүй: ${detail}` : `Сервер үйлдлийг гүйцэтгэсэнгүй (${response.status}).`;
  }
  async function request(path, body) {
    const options = {credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'}};
    if (state.token) options.headers['X-Admin-Token'] = state.token;
    if (body !== undefined) {options.method='POST';options.headers['Content-Type']='application/json';options.headers['X-Admin-Token']=state.token || '';options.body=JSON.stringify(body);}
    let response;
    try {response = await fetch(path, options);} catch (_) {throw new Error('Локал сервертэй холбогдож чадсангүй. Сервер ажиллаж байгаа эсэхийг шалгаарай.');}
    let result;
    try {result = await response.json();} catch (_) {throw new Error('Серверээс хүлээсэн мэдээлэл ирсэнгүй. Хуудсыг дахин ачаалж шалгаарай.');}
    if (!response.ok) throw new Error(errorText(response, result));
    return result;
  }
  async function readState() {
    const data = await request('/api/admin/state');
    if (!Array.isArray(data.releases) || typeof data.csrf_token !== 'string') throw new Error('Админы төлөв бүрэн ирсэнгүй. Серверийн хувилбарыг шалгаарай.');
    state.data = data; state.token = data.csrf_token; state.expected = activation(data); state.stale = false;
    state.content=null;$('reviewedCheckbox').checked=false;$('faqReviewed').checked=false;
    if (state.selected && !selected()) state.selected = null;
    render();
  }
  async function run(action) {
    if (state.busy) return;
    state.busy = true; document.body.setAttribute('aria-busy','true');show('errorNotice',false);renderButtons();
    try {await action();} catch (error) {message(error.message || 'Үйлдэл амжилтгүй боллоо.',true);} finally {state.busy=false;document.body.removeAttribute('aria-busy');renderButtons();}
  }
  function renderCounts(target, counts) {
    target.replaceChildren();
    const content=counts?.content || {}; const website=counts?.website || {};
    [['sources',content.sources],['facts',content.facts],['faqs',content.faqs],['indexed_chunks',website.indexed_chunks ?? website.indexed_passages ?? website.passages ?? website.chunks]].forEach(([key,value])=>{
      if (Number.isFinite(value)) {const node=element('span',metricNames[key]);node.prepend(element('strong',value));target.append(node);}
    });
  }
  function render() {
    show('workArea'); const active=state.data.active;
    show('activeErrorNotice',Boolean(state.data.active_error));
    if(state.data.active_error)setText('activeErrorNotice',`Идэвхтэй хувилбарыг уншихад алдаа гарсан тул чат түр хаалттай. Доороос өмнө нийтэлсэн хэвийн хувилбарыг сонгож буцааж болно. ${state.data.active_error}`);
    setText('activeLabel',active?.label || (active ? 'Нийтэлсэн хувилбар' : 'Төслийн анхны мэдээлэл'));
    setText('activeVersion',active ? `Хувилбар ${active.release_id}` : 'Одоогийн сангаас эхний шинэ хувилбарыг бэлтгэж болно.');
    renderCounts($('activeCounts'),active?.counts || state.data.legacy?.counts || state.data.baseline?.counts);
    const list=$('releaseList');list.replaceChildren();
    (state.data.releases || []).forEach(row=>{
      const button=element('button','',`release-item${row.release_id===state.selected?' selected':''}`);button.type='button';button.setAttribute('aria-pressed',String(row.release_id===state.selected));
      button.append(element('strong',row.label || 'Нэргүй хувилбар'),element('small',dateLabel(row.created_utc)));
      const label=row.release_id===activeId()?'Чат ашиглаж байна':published(row)?'Нийтэлсэн':validated(row)?'Шалгасан':row.status==='invalid'?'Алдаатай':'Ноорог';
      button.append(element('span',label,`badge${row.release_id===activeId()?' active':row.status==='invalid'?' invalid':''}`));
      button.addEventListener('click',()=>{if(state.busy)return;state.selected=row.release_id;state.content=null;state.imported=null;$('contentFile').value='';$('faqSelect').replaceChildren(element('option','Асуултаа сонгоорой'));$('faqSelect').firstChild.value='';setText('contentPreview','');$('reviewedCheckbox').checked=false;render();});
      list.append(button);
    });
    setText('releaseCount',`${state.data.releases.length}`);show('emptyReleases',!state.data.releases.length);
    const row=selected();show('editorArea',Boolean(row));show('sealedNote',locked(row));
    setText('selectedDescription',row ? `${row.label || 'Ноорог'} · ${row.release_id}` : 'Эхлээд ноорог бэлтгэх эсвэл жагсаалтаас сонгоорой.');
    show('faqEditor',Boolean(row) && state.contentSupported);show('faqForm',Boolean(state.content && $('faqSelect').value));
    renderReview(row);renderButtons();
  }
  function renderReview(row) {
    const validation=row?.validation;show('reviewResult',Boolean(validation));
    setText('validationStatus',!row?'Ноорог сонгоогүй.':published(row)?'Хадгалсан нийтлэл.':validated(row)?'Шалгалт тэнцсэн.':row.status==='invalid'?'Шалгалтын алдааг засах шаардлагатай.':'Оруулсан мэдээллээ шалгаарай.');
    if (!validation) {if(row?.error)message(`Ноорогт алдаа байна: ${row.error}`,true);return;}
    const changes=validation.changes || row.changes || {};
    setText('validationSummary',`Бүтцийн шалгалт тэнцсэн. ${changes.package_changed || changes.corpus_changed ? 'Доорх өөрчлөлтийг эхтэй нь нягтлаарай.' : 'Эхийн сан, хариултын агуулгын өөрчлөлт илрээгүй.'}`);
    const cards=$('countChanges');cards.replaceChildren();
    Object.entries(changes.counts || {}).forEach(([group,counts])=>{
      const card=element('div','','changes-card');card.append(element('h3',group==='website'?'Вэб ба баримтын эх':'FAQ ба баримт'));
      Object.entries(counts || {}).forEach(([key,value])=>{
        if(!value || !Number.isFinite(value.before) || !Number.isFinite(value.after))return;
        const line=element('div','','change-row');line.append(element('span',metricNames[key] || key),element('strong',`${value.before} → ${value.after}${value.delta ? ` (${value.delta>0?'+':''}${value.delta})` : ''}`));card.append(line);
      });if(card.children.length>1)cards.append(card);
    });
    if(!cards.children.length){const summary=validation.summary || {};[['website','Вэб ба баримтын эх'],['content','FAQ ба баримт']].forEach(([group,title])=>{const counts=summary[group]?.counts;if(!counts)return;const card=element('div','','changes-card');card.append(element('h3',title));Object.entries(counts).forEach(([key,value])=>{if(!Number.isFinite(value))return;const line=element('div','','change-row');line.append(element('span',metricNames[key] || key),element('strong',value));card.append(line);});cards.append(card);});}
    const source=$('sourceChanges');source.replaceChildren();
    Object.entries(groupNames).forEach(([group,label])=>{
      const diff=changes[group];if(!diff)return;
      [['added','Нэмэгдсэн'],['updated','Өөрчлөгдсөн'],['removed','Хасагдсан']].forEach(([kind,verb])=>{
        if(!Array.isArray(diff[kind]) || !diff[kind].length)return;
        const details=element('details');details.append(element('summary',`${label} · ${verb.toLowerCase()} ${diff[kind].length}`));
        const ul=element('ul');diff[kind].forEach(item=>ul.append(element('li',typeof item==='string'?item:item.title || item.document_id || item.faq_id || item.fact_id || item.url || JSON.stringify(item))));details.append(ul);source.append(details);
      });
    });
    Object.entries(changes.details || {}).forEach(([group,rows])=>{
      if(!Array.isArray(rows))return;
      rows.forEach(change=>{
        const details=element('details');details.append(element('summary',`${groupNames[group] || group} · ${change.id}`));
        [['before','Өмнөх агуулга'],['after','Шинэ агуулга']].forEach(([key,label])=>{
          const block=element('div','','diff-record');block.append(element('strong',label));const record=change[key];let text='Бүртгэл байхгүй.';
          if(record){if(group==='faqs')text=`${record.question || ''}\n\n${record.answer || ''}\n\nӨөрөөр асуух хувилбарууд:\n${(record.question_aliases || []).join('\n') || 'Байхгүй.'}\n\nЗасварын тайлбар: ${record.notes || 'Байхгүй.'}`;
          else if(group==='sources')text=`${record.title || ''}\n${record.source_url_or_filename || ''}\nХувилбар ${record.version} · татсан ${record.retrieved_at || 'тодорхойгүй'}\n${record.scope || ''}`;
          else text=`${record.key || ''}: ${typeof record.value==='string'?record.value:JSON.stringify(record.value)}\n${record.scope || ''}`;}
          block.append(element('p',text));
          if(record){const metadata=element('details','','record-metadata');metadata.append(element('summary','Эх, хамрах хүрээ, хугацаа зэрэг бүх талбар'),element('pre',JSON.stringify(record,null,2)));block.append(metadata);}
          details.append(block);
        });source.append(details);
      });
    });
    if(!source.children.length)source.append(element('p','Эхийн бүртгэлийн нэмэлт өөрчлөлт алга.','small muted'));
    show('rollbackButton',published(row) && row.release_id!==activeId());
    show('publishButton',!published(row));
    setText('publishHelp',row.release_id===activeId()?'Чат одоо энэ хувилбарыг ашиглаж байна.':published(row)?'Буцаахад чат энэ хадгалсан хувилбарыг дахин ашиглана.':'Нийтэлсний дараа чат болон эхийн сан шинэ мэдээллийг ашиглана.');
  }
  function renderButtons() {
    const row=selected(); const disabled=state.busy || !state.data || state.stale;
    $('stageButton').disabled=disabled; $('refreshButton').disabled=state.busy;
    $('validateButton').disabled=disabled || !row || locked(row);
    $('importContentButton').disabled=disabled || !row || locked(row) || !state.imported;
    $('importWebsiteButton').disabled=disabled || !row || locked(row);
    $('loadContentButton').disabled=disabled || !row;
    $('saveFaqButton').disabled=disabled || !row || locked(row) || !state.content || !$('faqReviewed').checked;
    ['contentFile','snapshotPath','faqSelect','faqQuestion','faqAnswer','faqAliases','faqNotes'].forEach(id=>$(id).disabled=disabled || !row || locked(row));
    $('faqReviewed').disabled=disabled || !row || locked(row);$('faqSelect').disabled=disabled || !row || !state.content;
    const reviewed=$('reviewedCheckbox').checked && $('actor').value.trim();
    const ready=!disabled && row && validated(row) && reviewed;
    $('publishButton').disabled=!ready || published(row);
    $('rollbackButton').disabled=!ready || !published(row) || row.release_id===activeId();
    show('staleNotice',state.stale);
    document.querySelectorAll('.release-item').forEach(button=>button.disabled=state.busy);
  }
  async function mutate(path,payload,success) {
    const response=await request(path,payload);const result=response.result || response;const id=result.release_id || result.release?.release_id || state.selected;
    state.content=null;$('faqForm').hidden=true;$('reviewedCheckbox').checked=false;
    await readState();if(id)state.selected=id;render();message(success);return result;
  }
  async function loadContent() {
    const row=selected();if(!row)return;
    let result;
    try {result=await request(`/api/admin/content?release_id=${encodeURIComponent(row.release_id)}`);} catch(error) {throw error;}
    const content=result.content || result;
    if(!Array.isArray(content.faqs) || !Array.isArray(content.sources) || !Array.isArray(content.facts))throw new Error('FAQ багцын бүтэц тохирсонгүй.');
    state.content=content;const select=$('faqSelect');select.replaceChildren(element('option','Асуултаа сонгоорой'));select.firstChild.value='';
    content.faqs.forEach((faq,index)=>{const option=element('option',faq.question || faq.faq_id);option.value=String(index);select.append(option);});
    show('faqForm',false);message(`${content.faqs.length} асуулт, хариултыг нооргоос уншлаа.`);renderButtons();
  }
  function selectFaq() {
    $('faqReviewed').checked=false;const value=$('faqSelect').value;const faq=value!==''?state.content?.faqs[Number(value)]:null;show('faqForm',Boolean(faq));if(!faq)return;
    $('faqQuestion').value=faq.question || '';$('faqAnswer').value=faq.answer || '';$('faqAliases').value=(faq.question_aliases || []).join('\n');$('faqNotes').value=faq.notes || '';
    const refs=$('faqRefs');refs.replaceChildren(element('strong','Тулгуур эх:'));
    (faq.source_refs || []).forEach(ref=>{
      const source=state.content.sources.find(item=>item.document_id===ref.document_id && item.version===ref.version);
      const block=element('div',`${source?.title || ref.document_id} · v${ref.version}\n`);
      if(source?.source_url_or_filename){
        let url;try{url=new URL(source.source_url_or_filename);}catch(_){}
        if(url?.protocol==='https:' && url.hostname==='nmct.edu.mn'){
          const link=element('a',url.href);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';block.append(link);
        }else block.append(element('span',source.source_url_or_filename));
      }
      block.append(element('p',ref.locator || ''));refs.append(block);
    });
    if(!(faq.source_refs || []).length)refs.append(element('p','Эх холбоогүй.'));renderButtons();
  }
  $('refreshButton').addEventListener('click',()=>run(async()=>{await readState();message('Одоогийн төлөвийг дахин уншлаа.');}));
  $('stageForm').addEventListener('submit',event=>{event.preventDefault();run(async()=>{await mutate('/api/admin/stage',{label:$('releaseLabel').value.trim(),expected_active:state.expected},'Ноорог бэлэн боллоо. Одоо мэдээллээ оруулж болно.');$('releaseLabel').value='';});});
  $('contentFile').addEventListener('change',()=>run(async()=>{
    state.imported=null;setText('contentPreview','');const file=$('contentFile').files[0];if(!file)return;
    if(file.size>2*1024*1024)throw new Error('JSON файл 2 MB-аас хэтэрсэн байна.');let content;try{content=JSON.parse(await file.text());}catch(_){throw new Error('JSON файлыг уншиж чадсангүй. Файлын бүтцийг шалгаарай.');}
    if(content?.schema_version!==1 || !['sources','facts','faqs'].every(key=>Array.isArray(content[key])))throw new Error('Файлд schema_version: 1, sources, facts, faqs гэсэн мэдээлэл байх ёстой.');
    state.imported=content;setText('contentPreview',`${file.name} · ${content.sources.length} эх · ${content.facts.length} баримт · ${content.faqs.length} FAQ. Оруулахад энэ багц нооргийн хариултын сан болно.`);
  }));
  $('contentForm').addEventListener('submit',event=>{event.preventDefault();if(!state.imported)return;run(async()=>{await mutate('/api/admin/import-content',{release_id:state.selected,content:state.imported},'JSON багцыг ноорогт орууллаа. Одоо өөрчлөлтийг шалгаарай.');state.imported=null;$('contentFile').value='';setText('contentPreview','');});});
  $('websiteForm').addEventListener('submit',event=>{event.preventDefault();run(()=>mutate('/api/admin/import-website',{release_id:state.selected,snapshot_path:$('snapshotPath').value.trim()},'Хадгалсан вэб эхийг ноорогт орууллаа. Одоо өөрчлөлтийг шалгаарай.'));});
  $('validateButton').addEventListener('click',()=>run(()=>mutate('/api/admin/validate',{release_id:state.selected},'Бүтцийн шалгалт тэнцлээ. Доорх өөрчлөлтийг эхтэй нь нягтлаарай.')));
  $('loadContentButton').addEventListener('click',()=>run(loadContent));$('faqSelect').addEventListener('change',selectFaq);
  $('faqForm').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
    if(!state.content || $('faqSelect').value==='' || !$('faqReviewed').checked)return;const content=JSON.parse(JSON.stringify(state.content));const faq=content.faqs[Number($('faqSelect').value)];
    faq.question=$('faqQuestion').value.trim();faq.answer=$('faqAnswer').value.trim();faq.question_aliases=$('faqAliases').value.split('\n').map(item=>item.trim()).filter(Boolean);faq.notes=$('faqNotes').value.trim();
    await mutate('/api/admin/import-content',{release_id:state.selected,content},'Хариултын засварыг ноорогт хадгаллаа. Өөрчлөлтийг шалгах товчоор үргэлжлүүлээрэй.');
  });});
  async function activate(kind) {const row=selected();if(!row)return;await mutate(`/api/admin/${kind}`,{release_id:row.release_id,expected_active:state.expected,actor:$('actor').value.trim()},kind==='rollback'?'Өмнөх хувилбарт буцаалаа. Чат, эхийн сангаас мэдээллээ шалгаж болно.':'Шинэ мэдээллийг нийтэллээ. Чат, эхийн сангаас шинэчлэлээ шалгаж болно.');}
  $('publishButton').addEventListener('click',()=>run(()=>activate('publish')));$('rollbackButton').addEventListener('click',()=>run(()=>activate('rollback')));
  $('reviewedCheckbox').addEventListener('change',renderButtons);$('actor').addEventListener('input',renderButtons);
  $('faqReviewed').addEventListener('change',renderButtons);
  ['faqQuestion','faqAnswer','faqAliases','faqNotes'].forEach(id=>$(id).addEventListener('input',()=>{$('faqReviewed').checked=false;renderButtons();}));
  run(readState);
})();
