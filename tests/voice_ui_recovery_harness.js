// Execute the actual browser handlers with a controlled DOM, clock and fetch.
// No browser, server, provider, recording or model is contacted.
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const scenario = process.argv[3];
const inline = source.match(/<script>([\s\S]*?)<\/script>/);
assert(inline, 'The actual page must contain its inline browser script');
new vm.Script(inline[1], {filename: 'actual-demo-inline-script.js'});
function between(start, end) {
  const left = source.indexOf(start), right = source.indexOf(end, left + start.length);
  assert(left >= 0 && right > left, `Missing actual UI section ${start}`);
  return source.slice(left, right);
}
const elements = new Map(), handlers = new Map(), requests = [], timers = [], discarded = [], cleanupRequests = [];
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', textContent: '', hidden: false, disabled: false, checked: false,
    pause() {}, load() {}, removeAttribute() {}, replaceChildren() {},
    append() {}, querySelector() { return element(id + '-button'); },
    addEventListener(kind, handler) { handlers.set(id + ':' + kind, handler); }
  });
  return elements.get(id);
}
let ignoreAbort = false;
const context = vm.createContext({
  $, AbortController, console, Set, Number, Error,
  navigator: {mediaDevices: {getUserMedia() {}}},
  window: {MediaRecorder: function(){}, addEventListener(kind, handler) { handlers.set('window:' + kind, handler); }},
  document: {querySelectorAll() { return []; }, body: {append() {}}},
  setTimeout(fn, milliseconds) { const timer = {fn, milliseconds, cleared: false}; timers.push(timer); return timer; },
  clearTimeout(timer) { if (timer) timer.cleared = true; },
  fetch(path, options={}) {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    const request = {path, options, resolve, reject}; requests.push(request);
    if (options.signal && !ignoreAbort) options.signal.addEventListener('abort', () =>
      reject(Object.assign(new Error('controlled abort'), {name: 'AbortError'})), {once: true});
    return promise;
  },
  api(path, body) {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve=yes; reject=no; });
    cleanupRequests.push({path,body,resolve,reject}); return promise;
  },
  clearCorrection() {}, clearSpeech() {}, sizeComposer() {},
  clearInput() { vm.runInContext('selectedAudio=null', context); },
  refreshClarificationHint() {}, discardClarifications() {}, stopMic() {}, resetPreview() {},
  async discardVoice(ids) { discarded.push(...ids); },
  ownResponse(result) { context.savedIds.push(result.id); }, savedIds: [],
  node() { return {append() {}}; }, scrollChat() {},
  appendTurn(query,draft) { return {query,draft,body:element('testTurnBody'),transcriptionId:run('currentTranscription?.id')}; },
  acceptClarification() {}, renderTurn() {},
});
function $(id) { return element(id); }
vm.runInContext(`
  let geminiSessionToken='fixture-token';
  let voiceState={stt_ready:true,tts_ready:true},llmState={},voiceBusy=false,
      voiceGeneration=0,routeGeneration=0,routeBusy=false,micStarting=false,
      micRecorder=null,selectedAudio={type:'audio/wav'},currentTranscription=null,
      latestRoute=null,pendingClarification=null,websiteGeneration=0,faqGeneration=0,
      correctionBusy=false,correctionGeneration=0,correctionValue=null,activeCorrection=null;
  const ownedVoiceIds=new Set(),ownedClarificationIds=new Set(),chatTurns=[];
`, context);
vm.runInContext(between('function hasSpokenReply', 'function speakTurn'), context);
const state = source.match(/^const STT_REQUEST_TIMEOUT_MS=.*$/m);
if (state) vm.runInContext(state[0], context);
const active = source.match(/^let activeTranscription=.*$/m);
if (active) vm.runInContext(active[0], context);
if (source.includes('function cancelTranscription()'))
  vm.runInContext(between('function cancelTranscription()', 'function invalidateVoiceAnswer'), context);
vm.runInContext(between('function invalidateVoiceAnswer', 'async function discardVoice'), context);
vm.runInContext(between('async function transcribeSelected()', '$("voiceFile").addEventListener'), context);
vm.runInContext(between('function clearCorrection()', 'async function loadReviews()'), context);
vm.runInContext(source.split(/\r?\n/).find(line => line.startsWith('$("routeQuery").addEventListener("input"')), context);
vm.runInContext(between('async function askTurn(turn)', '$("routeQuery").addEventListener("keydown"'), context);
vm.runInContext(source.split(/\r?\n/).find(line => line.startsWith('$("voiceReset").addEventListener')), context);
vm.runInContext(source.split(/\r?\n/).find(line => line.startsWith('$("removeCapture").addEventListener')), context);
vm.runInContext(source.split(/\r?\n/).find(line => line.startsWith('window.addEventListener("pagehide"')), context);
if (scenario.startsWith('cleanup-')) {
  vm.runInContext(between('async function discardVoice', 'function ownResponse'), context);
  vm.runInContext(source.split(/\r?\n/).find(line => line.startsWith('function ownResponse')), context);
}

const run = expression => vm.runInContext(expression, context);
const success = (request, text, id = 'a'.repeat(32)) => request.resolve({ok: true,
  async json() { return {id, text, speech_text_available: !!text,
    model_load_seconds: 0, transcription_seconds: 1, audio_seconds: 2}; }});
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const bindCorrection = (text='сургуулийн тухай мэдээлэл авмаар байн', id='a'.repeat(32)) => {
  element('routeQuery').value=text;
  context.boundRaw=text;context.boundId=id;
  run('llmState={configured:true,available:true};currentTranscription={id:boundId,rawText:boundRaw};refreshVoiceControls()');
};
const correctionReply = (request, overrides={}) => request.resolve({ok:true,async json(){
  const raw=JSON.parse(request.options.body).text;
  return {raw_text:raw,suggested_text:raw+'а',automatic_application:false,
    used:true,changed:true,guard_rejected:false,message:'controlled guarded suggestion',...overrides};
}});

async function main() {
  if (scenario === 'gemini') {
    element('sttProvider').value='gemini';
    run('voiceState.gemini={ready:true,remaining_attempts:2};llmState={configured:true,available:true}');
    await run('transcribeSelected()');
    assert.equal(requests.length,0,'No cloud audio request without this-clip consent');
    element('geminiConsent').checked=true;
    const pending=run('transcribeSelected()');
    assert.equal(requests[0].path,'/api/voice/transcribe');
    assert.equal(requests[0].options.headers['X-STT-Provider'],'gemini');
    assert.equal(requests[0].options.headers['X-Gemini-Audio-Consent'],'send-this-audio');
    assert.equal(requests[0].options.headers['X-Gemini-Token'],'fixture-token');
    requests[0].resolve({ok:true,async json(){return {id:'a'.repeat(32),text:'fixture cloud raw',provider:'google_gemini',model:'gemini-3.5-transcribe',speech_text_available:true,model_load_seconds:0,transcription_seconds:1,audio_seconds:2}}});
    await pending;await flush();
    assert.equal(element('geminiConsent').checked,false,'One consent is consumed per attempted clip');
    assert(element('sttTiming').textContent.includes('Gemini 3.5 Transcribe'));
    assert.equal(requests.filter(r=>r.path==='/api/voice/correct').length,0,'Cloud raw text receives no automatic local rewrite');
    assert.equal(requests[1].path,'/api/voice/gemini/session');
    requests[1].resolve({ok:true,async json(){return {csrf_token:'fixture-token',ready:true,remaining_attempts:1}}});
    await flush();
    assert.equal(element('routeQuery').value,'fixture cloud raw');
    console.log(JSON.stringify({scenario,passed:true,network_calls:0,model_calls:0,source_handlers_executed:true}));
    return;
  }
  if (scenario === 'correction-auto') {
    run('llmState={configured:true,available:true}');
    const pending=run('transcribeSelected()');
    success(requests[0],'сургуулийн тухай мэдээлэл авмаар байн');await pending;
    assert.equal(requests.length,2,'Successful STT automatically requests one optional suggestion');
    assert.equal(requests[1].path,'/api/voice/correct');
    assert.equal(element('routeQuery').value,'сургуулийн тухай мэдээлэл авмаар байн');
    assert.equal(element('sttOriginal').textContent,element('routeQuery').value);
    assert.equal(run('voiceBusy'),false);assert.equal(run('correctionBusy'),true);
    assert.equal(element('routeQuery').disabled,false,'Raw text is immediately editable');
    assert.equal(element('routeButton').disabled,false,'Suggestion never blocks Send');
    assert.equal(element('attachAudio').disabled,false,'A new audio input does not wait for the LLM');
    correctionReply(requests[1]);await flush();
    assert.equal(element('correctionSuggestion').hidden,false);
    assert.equal(element('routeQuery').value,run('currentTranscription.rawText'),'A proposal does not apply itself');
    handlers.get('applyCorrectionButton:click')();
    assert.equal(element('routeQuery').value,'сургуулийн тухай мэдээлэл авмаар байна');
    assert.equal(run('currentTranscription.rawText'),'сургуулийн тухай мэдээлэл авмаар байн');
    assert.equal(run('currentTranscription.id'),'a'.repeat(32));
    assert.equal(element('sttOriginal').textContent,'сургуулийн тухай мэдээлэл авмаар байн');
  } else if (scenario === 'correction-edit-late') {
    bindCorrection();ignoreAbort=true;const first=run('requestCorrection({automatic:true})');
    element('routeQuery').value='хэрэглэгчийн өөрийн засвар';handlers.get('routeQuery:input')();
    assert.equal(requests[0].options.signal.aborted,true);
    const newer=run('requestCorrection()');assert.equal(requests.length,2);
    correctionReply(requests[0]);await first;
    assert.equal(run('correctionBusy'),true,'Older finally cannot unlock a new correction');
    assert.equal(element('routeQuery').value,'хэрэглэгчийн өөрийн засвар');
    assert.equal(element('correctionSuggestion').hidden,true);
    correctionReply(requests[1]);await newer;
    assert.equal(element('correctionText').textContent,'хэрэглэгчийн өөрийн засвара');
  } else if (scenario === 'correction-new-audio') {
    bindCorrection();ignoreAbort=true;const first=run('requestCorrection()');
    const stt=run('transcribeSelected()');assert.equal(requests[0].options.signal.aborted,true);
    correctionReply(requests[0]);await first;
    assert.equal(run('voiceBusy'),true);assert.equal(element('routeQuery').disabled,true);
    assert.equal(element('correctionSuggestion').hidden,true);
    success(requests[1],'шинэ дууны текст','b'.repeat(32));await stt;
    assert.equal(requests.length,3);assert.equal(requests[2].path,'/api/voice/correct');
    assert.equal(run('currentTranscription.id'),'b'.repeat(32));
    correctionReply(requests[2]);await flush();assert.equal(element('correctionText').textContent,'шинэ дууны текста');
  } else if (scenario === 'correction-reset') {
    bindCorrection();ignoreAbort=true;const pending=run('requestCorrection()');
    await handlers.get('voiceReset:click')();
    assert.equal(requests[0].options.signal.aborted,true);
    correctionReply(requests[0]);await pending;
    assert.equal(element('routeQuery').value,'');assert.equal(run('currentTranscription'),null);
    assert.equal(run('correctionBusy'),false);assert.equal(element('correctionSuggestion').hidden,true);
    assert.equal(element('correctionStatus').textContent,'');
  } else if (scenario === 'correction-send') {
    bindCorrection();ignoreAbort=true;const pending=run('requestCorrection()');
    handlers.get('routeForm:submit')({preventDefault(){}});
    assert.equal(requests[0].options.signal.aborted,true);
    assert.equal(run('routeBusy'),true);assert.equal(run('currentTranscription'),null);
    assert.equal(cleanupRequests.at(-1).path,'/api/route');
    assert.equal(cleanupRequests.at(-1).body.transcription_id,'a'.repeat(32),'Send preserves audio lineage while canceling a suggestion');
    correctionReply(requests[0]);await pending;
    assert.equal(element('routeQuery').value,'');assert.equal(element('correctionSuggestion').hidden,true);
    cleanupRequests.at(-1).resolve({query:'controlled query'});await flush();
    assert.equal(run('routeBusy'),false);
  } else if (scenario === 'correction-timeout') {
    bindCorrection();const pending=run('requestCorrection()');
    const timer=timers.find(t=>t.milliseconds===25000&&!t.cleared);assert(timer);
    timer.fn();await pending;
    assert.equal(requests[0].options.signal.aborted,true);assert.equal(run('correctionBusy'),false);
    assert.equal(element('routeButton').disabled,false);assert.equal(element('routeQuery').disabled,false);
    assert.equal(element('routeQuery').value,run('currentTranscription.rawText'));
    assert.match(element('correctionStatus').textContent,/хугацаа/);
  } else if (scenario === 'correction-body-late') {
    bindCorrection();let bodyResolve;const body=new Promise(resolve=>bodyResolve=resolve);
    const pending=run('requestCorrection()');requests[0].resolve({ok:true,json(){return body}});await flush();
    element('routeQuery').value='зассан текст';handlers.get('routeQuery:input')();
    bodyResolve({raw_text:context.boundRaw,suggested_text:'хуучин санал',used:true,changed:true,automatic_application:false});await pending;
    assert.equal(element('routeQuery').value,'зассан текст');assert.equal(element('correctionSuggestion').hidden,true);
    assert.equal(element('correctionStatus').textContent,'');
  } else if (scenario === 'correction-apply-binding') {
    bindCorrection();const pending=run('requestCorrection()');correctionReply(requests[0]);await pending;
    assert.equal(element('correctionSuggestion').hidden,false);
    run("currentTranscription={id:'b'.repeat(32),rawText:boundRaw}");handlers.get('applyCorrectionButton:click')();
    assert.equal(element('routeQuery').value,context.boundRaw,'A new audio ID invalidates an identical-text proposal');
    run('currentTranscription={id:boundId,rawText:boundRaw}');element('routeQuery').value='direct programmatic edit';
    handlers.get('applyCorrectionButton:click')();assert.equal(element('routeQuery').value,'direct programmatic edit');
  } else if (scenario === 'correction-bad-response') {
    for(const overrides of [{raw_text:'wrong raw'},{automatic_application:true},{guard_rejected:true},{used:false},{changed:false}]){
      bindCorrection();const before=requests.length;const pending=run('requestCorrection()');correctionReply(requests[before],overrides);await pending;
      assert.equal(element('routeQuery').value,context.boundRaw);assert.equal(element('correctionSuggestion').hidden,true);
      assert.equal(run('correctionBusy'),false);assert.equal(element('routeButton').disabled,false);
    }
  } else if (scenario === 'correction-failure-retry') {
    bindCorrection();const pending=run('requestCorrection()');requests[0].reject(new Error('controlled offline'));await pending;
    assert.equal(element('routeQuery').value,context.boundRaw);assert.equal(element('correctTranscriptButton').disabled,false);
    const retry=handlers.get('correctTranscriptButton:click')();assert.equal(requests.length,2);
    correctionReply(requests[1]);await retry;assert.equal(element('correctionSuggestion').hidden,false);
    assert.equal(element('routeQuery').value,context.boundRaw);
  } else if (scenario === 'correction-empty-unavailable') {
    run('llmState={configured:true,available:true}');const empty=run('transcribeSelected()');success(requests[0],'');await empty;
    assert.equal(requests.length,1,'Empty speech never becomes a correction request');
    run('llmState={configured:true,available:false}');const unavailable=run('transcribeSelected()');success(requests[1],'таньсан текст');await unavailable;
    assert.equal(requests.length,2,'Unavailable LLM never delays successful raw STT');
    assert.equal(element('routeQuery').value,'таньсан текст');assert.equal(element('routeButton').disabled,false);
    run('llmState={configured:false,available:false}');await run('requestCorrection()');assert.equal(requests.length,2);
  } else if (scenario === 'correction-provider-recovery') {
    bindCorrection();run('llmState.available=false;refreshVoiceControls()');
    await run('requestCorrection({automatic:true})');assert.equal(requests.length,0,'Unavailable service is not automatically retried');
    assert.equal(element('correctTranscriptButton').hidden,false,'A configured temporary outage must leave a manual retry');
    assert.equal(element('correctTranscriptButton').disabled,false);
    const retry=handlers.get('correctTranscriptButton:click')();assert.equal(requests.length,1);
    correctionReply(requests[0],{available:true});await retry;
    assert.equal(run('llmState.available'),true,'An actual successful reply can restore future automatic suggestions');
    assert.equal(element('correctionSuggestion').hidden,false);
    assert.equal(element('routeQuery').value,context.boundRaw);
  } else if (scenario === 'correction-programmatic-busy') {
    bindCorrection();
    for(const state of ['routeBusy=true','voiceBusy=true','micStarting=true',"micRecorder={state:'recording'}"]){
      run('routeBusy=false;voiceBusy=false;micStarting=false;micRecorder=null;'+state);
      await run('requestCorrection()');assert.equal(requests.length,0,'Disabled-control state is also guarded inside the handler');
    }
  } else if (scenario === 'correction-pagehide') {
    bindCorrection();const pending=run('requestCorrection()');handlers.get('window:pagehide')();await pending;
    assert.equal(requests[0].options.signal.aborted,true);assert.equal(run('correctionBusy'),false);
    assert.equal(element('correctionSuggestion').hidden,true);
  } else if (scenario === 'timeout') {
    const pending = run('transcribeSelected()');
    assert.equal(requests.length, 1);
    const timer = timers.find(item => item.milliseconds === 120000 && !item.cleared);
    assert(timer, 'STT must have a bounded browser deadline');
    assert(requests[0].options.signal, 'STT fetch must carry its AbortSignal');
    timer.fn(); await pending;
    assert.equal(run('voiceBusy'), false);
    assert.equal(element('routeQuery').disabled, false);
    assert.equal(run('currentTranscription'), null);
    assert(run('selectedAudio'), 'Timeout must preserve the selected audio for retry');
    assert.match(element('voiceStatus').textContent, /хугацаа/);
    assert.equal(timer.cleared, true);
  } else if (scenario === 'reset') {
    const pending = run('transcribeSelected()');
    await handlers.get('voiceReset:click')(); await flush();
    assert.equal(run('voiceBusy'), false, 'Reset must release only the canceled STT operation');
    assert.equal(element('routeQuery').disabled, false);
    assert.equal(requests[0].options.signal.aborted, true);
    await pending;
    assert.equal(element('voiceStatus').textContent, '');
    assert.equal(run('currentTranscription'), null);
    run("selectedAudio={type:'audio/wav'}");
    const leaving = run('transcribeSelected()');
    handlers.get('window:pagehide')(); await leaving;
    assert.equal(run('voiceBusy'), false);
    assert.equal(requests[1].options.signal.aborted, true);
  } else if (scenario === 'late') {
    ignoreAbort = true; // A remote server can finish even after browser cancellation.
    const first = run('transcribeSelected()');
    await handlers.get('voiceReset:click')();
    run("selectedAudio={type:'audio/wav'}");
    const second = run('transcribeSelected()');
    assert.equal(requests.length, 2, 'A new STT request must work after reset');
    success(requests[0], 'OLD', 'a'.repeat(32)); await first;
    assert.equal(run('voiceBusy'), true, 'Old finally must not unlock the newer request');
    assert.equal(element('routeQuery').value, '');
    assert.equal(run('currentTranscription'), null);
    assert(discarded.includes('a'.repeat(32)), 'A received stale audio ID must be cleaned up');
    success(requests[1], 'NEW', 'b'.repeat(32)); await second;
    assert.equal(element('routeQuery').value, 'NEW');
    assert.equal(run('currentTranscription.id'), 'b'.repeat(32));
    assert.equal(run('voiceBusy'), false);
  } else if (scenario === 'replace') {
    ignoreAbort = true;
    const first = run('transcribeSelected()');
    handlers.get('removeCapture:click')();
    assert.equal(run('voiceBusy'), false);
    assert.equal(requests[0].options.signal.aborted, true);
    assert.equal(run('selectedAudio'), null);
    run("selectedAudio={type:'audio/ogg'}");
    const second = run('transcribeSelected()');
    requests[0].reject(new Error('obsolete error')); await first;
    assert.equal(run('voiceBusy'), true);
    assert.notEqual(element('voiceStatus').textContent, 'obsolete error');
    success(requests[1], 'REPLACEMENT'); await second;
    assert.equal(element('routeQuery').value, 'REPLACEMENT');
    assert.equal(run('voiceBusy'), false);
  } else if (scenario === 'json') {
    let pending = run('transcribeSelected()');
    requests[0].resolve({ok:true, async json() { throw new Error('controlled JSON failure'); }});
    await pending;
    assert.equal(run('voiceBusy'), false);
    assert.equal(element('voiceStatus').textContent, 'controlled JSON failure');
    assert.equal(context.savedIds.length, 0);
    let resolveBody;
    const body = new Promise(resolve => { resolveBody = resolve; });
    pending = run('transcribeSelected()');
    requests[1].resolve({ok:true, json() { return body; }}); await flush();
    await handlers.get('voiceReset:click')();
    run("selectedAudio={type:'audio/wav'}");
    const newest = run('transcribeSelected()');
    resolveBody({id:'c'.repeat(32),text:'LATE BODY'}); await pending;
    assert.equal(run('voiceBusy'), true);
    assert.equal(element('routeQuery').value, '');
    assert(discarded.includes('c'.repeat(32)));
    success(requests[2], 'CURRENT BODY'); await newest;
    assert.equal(element('routeQuery').value, 'CURRENT BODY');
  } else if (scenario === 'network') {
    const pending = run('transcribeSelected()');
    requests[0].reject(new Error('controlled network loss')); await pending;
    assert.equal(run('voiceBusy'), false);
    assert.equal(element('routeQuery').disabled, false);
    assert.equal(element('voiceStatus').textContent, 'controlled network loss');
    const retry = run('transcribeSelected()');
    success(requests[1], 'RECOVERED'); await retry;
    assert.equal(element('routeQuery').value, 'RECOVERED');
  } else if (scenario === 'lineage') {
    const pending = run('transcribeSelected()');
    success(requests[0], 'Анхны танилт'); await pending;
    assert.equal(run('currentTranscription.rawText'), 'Анхны танилт');
    element('routeQuery').value = 'Гараар зассан текст';
    assert.equal(run('currentTranscription.rawText'), 'Анхны танилт');
    assert.equal(run('currentTranscription.id'), 'a'.repeat(32));
    assert.equal(run('voiceBusy'), false);
    assert(timers.every(timer => timer.cleared));
  } else if (scenario === 'http-empty') {
    let pending = run('transcribeSelected()');
    requests[0].resolve({ok:false, async json() { return {error:'controlled STT503'}; }});
    await pending;
    assert.equal(run('currentTranscription'), null);
    assert.equal(context.savedIds.length, 0);
    assert.equal(run('voiceBusy'), false);
    pending = run('transcribeSelected()');
    success(requests[1], ''); await pending;
    assert.equal(run('currentTranscription'), null);
    assert.equal(element('routeQuery').value, '');
    assert.equal(run('voiceBusy'), false);
  } else if (scenario === 'cleanup-retry') {
    run("ownResponse({id:'a'.repeat(32)})");
    let pending = run('discardVoice([...ownedVoiceIds])');
    assert.equal(cleanupRequests.length, 1);
    cleanupRequests[0].reject(new Error('controlled cleanup loss')); await pending;
    assert.equal(run("ownedVoiceIds.has('a'.repeat(32))"), true,
      'A failed cleanup must preserve its IDs for a later normal reset');
    await flush(); assert.equal(cleanupRequests.length, 1, 'No automatic retry loop');
    pending = run('discardVoice([...ownedVoiceIds])');
    assert.deepEqual(Array.from(cleanupRequests[1].body.ids), ['a'.repeat(32)]);
    cleanupRequests[1].resolve({deleted_ids:['a'.repeat(32)]}); await pending;
    assert.equal(run('ownedVoiceIds.size'), 0);
    await run('discardVoice([])'); assert.equal(cleanupRequests.length, 2);
  } else if (scenario === 'cleanup-concurrent') {
    run("ownResponse({id:'a'.repeat(32)})");
    const first = run('discardVoice([...ownedVoiceIds])');
    assert.equal(run("ownedVoiceIds.has('a'.repeat(32))"), true, 'Pending acknowledgment retains ownership');
    run("ownResponse({id:'b'.repeat(32)})");
    const second = run("discardVoice(['b'.repeat(32)])");
    cleanupRequests[1].resolve({deleted_ids:['b'.repeat(32)]}); await second;
    run("ownResponse({id:'c'.repeat(32)})");
    cleanupRequests[0].resolve({deleted_ids:['a'.repeat(32)]}); await first;
    assert.equal(run('ownedVoiceIds.size'), 1);
    assert.equal(run("ownedVoiceIds.has('c'.repeat(32))"), true,
      'An older acknowledgment must not erase a newly created audio ID');
    assert.deepEqual(Array.from(cleanupRequests[0].body.ids), ['a'.repeat(32)]);
    assert.deepEqual(Array.from(cleanupRequests[1].body.ids), ['b'.repeat(32)]);
  } else if (scenario === 'cleanup-batch') {
    run("for(let i=0;i<125;i++)ownedVoiceIds.add(i.toString(16).padStart(32,'0'))");
    const pending = run('discardVoice([...ownedVoiceIds])');
    assert.equal(cleanupRequests[0].body.ids.length, 100);
    cleanupRequests[0].resolve({deleted_ids:[]}); await flush();
    assert.equal(cleanupRequests.length, 2);
    assert.equal(cleanupRequests[1].body.ids.length, 25);
    assert.equal(run('ownedVoiceIds.size'), 25);
    cleanupRequests[1].resolve({deleted_ids:[]}); await pending;
    assert.equal(run('ownedVoiceIds.size'), 0);
    assert(cleanupRequests.every(request => request.path === '/api/voice/reset'));
  } else if (scenario === 'cleanup-reset') {
    run("ownResponse({id:'a'.repeat(32)})");
    const pending = handlers.get('voiceReset:click')();
    assert.equal(cleanupRequests.length, 1, 'One normal reset must not duplicate its pending cleanup call');
    assert.equal(element('routeQuery').disabled, false, 'Cleanup latency must not keep the composer locked');
    run("ownResponse({id:'b'.repeat(32)})");
    cleanupRequests[0].resolve({deleted_ids:['a'.repeat(32)]}); await pending;
    assert.equal(run("ownedVoiceIds.has('b'.repeat(32))"), true);
    assert.equal(run('ownedVoiceIds.size'), 1);
  } else if (scenario === 'cleanup-pagehide') {
    run("for(let i=0;i<125;i++)ownedVoiceIds.add(i.toString(16).padStart(32,'0'))");
    handlers.get('window:pagehide')();
    assert.equal(requests.length, 2, 'Pagehide cleanup must also obey the 100-ID API limit');
    assert.deepEqual(requests.map(request => JSON.parse(request.options.body).ids.length), [100,25]);
    assert(requests.every(request => request.path === '/api/voice/reset' && request.options.keepalive === true));
    assert.equal(run('ownedVoiceIds.size'), 125);
    run("ownResponse({id:'f'.repeat(32)})");
    requests[0].resolve({ok:true}); await flush();
    requests[1].reject(new Error('controlled keepalive loss')); await flush();
    assert.equal(run('ownedVoiceIds.size'), 26);
    assert.equal(run("ownedVoiceIds.has('f'.repeat(32))"), true);
  } else throw new Error('Unknown scenario');
  console.log(JSON.stringify({scenario, passed:true, fetch_calls:requests.length,
    cleanup_api_calls:cleanupRequests.length, network_calls:0, model_calls:0, source_handlers_executed:true}));
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
