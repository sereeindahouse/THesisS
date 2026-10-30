/* Real study-page event handlers in a synthetic DOM. No human data or models. */
'use strict';
const vm=require('vm'),assert=require('assert'),fs=require('fs');
const source=fs.readFileSync(0,'utf8');
class Element{
  constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.textContent='';this.checked=false;this.disabled=false;this.attrs={};this.classList={add:()=>{},remove:()=>{}};}
  append(n){this.children.push(n)}
  replaceChildren(...nodes){this.children=[...nodes]}
  setAttribute(k,v){this.attrs[k]=v}
  focus(){this.focused=true}
  scrollIntoView(){this.scrolled=true}
}
const elements=new Map(),stored=new Map([['humanTrialSession','fixture-session']]),calls=[],checks=[];
const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
const state={csrf_token:'fixture-csrf',answer_ready:false,answers:[],listening:[],completed_listening:[],completed_reviews:[],audio_storage_consent:true,listening_text_scope:'constructed scope',active_task:null};
let nextReply=null,reloaded=0;
const context=vm.createContext({console,document:{getElementById:get,createElement:tag=>new Element(tag)},
 sessionStorage:{getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},
 fetch:async(url,options={})=>{calls.push({url,options});const r=nextReply;nextReply=null;return {ok:r?r.ok:true,json:async()=>r?r.value:state}},
 window:{addEventListener:()=>{}},location:{reload:()=>{reloaded++}},Date,Blob,setInterval:()=>123,clearInterval:()=>{},
 navigator:{mediaDevices:{getUserMedia:async()=>{throw Error('No real microphone in fixture')}}}});
async function run(code){return await vm.runInContext(code,context)}
(async()=>{
 vm.runInContext(source,context);await new Promise(resolve=>setImmediate(resolve));
 const task={task_id:'fixture-task',intended_request:'Constructed original intent',context:{device:'fixture',room:'fixture',scenario:'fixture'},
  recording:{audio_sha256:'a'.repeat(64),duration_seconds:12,audio_url:'/api/task-recording/fixture'},reference:null,
  reference_draft:{text:'Constructed heard words',uncertainties:['unclear year']},transcription_attempted:false,transcript:null,
  results:[{condition:'typed',answer:'Constructed answer',observation_saved:true}]};
 await run('restoreTask('+JSON.stringify(task)+')');
 assert.equal(get('recordedAudio').src,task.recording.audio_url);assert.equal(get('reference').value,task.reference_draft.text);
 assert.equal(get('uncertainties').value,'unclear year');assert(get('recognize').disabled);assert(get('typed').disabled);
 checks.push('Reload restores retained recording, draft, typed result; no invented reference or ASR');
 const before=calls.length;await run("referenceHeard=false; $('saveReference').onclick()");
 assert.equal(calls.length,before);assert(get('referenceHelp').textContent.includes('бүтнээр'));
 checks.push('Incomplete playback blocks reference submission beside the button');
 await run("referenceHeard=true; $('referenceConfirmed').checked=true");
 nextReply={ok:true,value:{saved:true,reference_confirmed_before_asr:false,unresolved_count:1}};
 await run("$('saveReference').onclick()");
 assert(get('recognize').disabled);assert(get('referenceHelp').textContent.includes('1 мөр'));assert(get('uncertainties').focused);
 assert.equal(get('uncertainties').attrs['aria-invalid'],'true');assert.equal(get('uncertainties').value,'unclear year');
 checks.push('Uncertainty stays intact, is identified inline and cannot silently open ASR');
 await run("$('uncertainties').value=''; $('referenceConfirmed').checked=true");
 nextReply={ok:true,value:{saved:true,reference_confirmed_before_asr:true}};
 await run("$('saveReference').onclick()");
 assert(!get('recognize').disabled);assert(get('reference').disabled);assert(get('saveReference').disabled);
 assert(get('referenceHelp').textContent.includes('нээгдлээ'));
 assert.equal(JSON.parse(calls.at(-1).options.body).confirmed,true);
 checks.push('Explicit confirmation freezes the reference and visibly opens the Gemini action');
 nextReply={ok:false,value:{error:'Бичлэг 30 секундээс урт байна.'}};
 await run("busy=true; saveStoppedRecording(new Blob(['fixture audio'],{type:'audio/webm'}))");
 assert.equal(calls.at(-1).url,'/api/task/record');assert(!get('record').disabled);assert(!get('upload').disabled);
 assert(get('recordStatus').textContent.includes('30 секунд'));assert.equal(await run('recordingSaving'),false);
 checks.push('Recorder stop saves even while another UI action is busy; decode failure restores retry controls');
 await run("busy=false; recordingSaving=true; $('nextTask').onclick()");assert.equal(reloaded,0);
 await run("recordingSaving=false; recording={state:'recording'}; $('nextTask').onclick()");assert.equal(reloaded,0);
 await run("recording=null; $('nextTask').onclick()");assert.equal(reloaded,1);assert.equal(stored.get('humanTrialNewTask:fixture-session'),'1');
 checks.push('New-task reload cannot discard an active/saving recording and retains the consented session');
 assert(calls.every(c=>!c.url.includes('transcribe')));
 checks.push('UI recovery and reference checks never invoke a model or fabricate human ratings');
 const measurement={raw_score:{corpus_wer:.25,corpus_cer:.1,word_edit_errors:1,reference_words:4},wall_seconds:2,cache_hit:false};
 nextReply={ok:true,value:{text:'fixture Gemini raw',measurement,provider:'google_gemini_live'}};
 await run("$('recognize').onclick()");
 assert.equal(calls.at(-1).url,'/api/task/transcribe');
 assert.equal(JSON.parse(calls.at(-1).options.body).cloud_audio_consent,true);
 assert(get('measurement').textContent.includes('25.0%'));
 assert(get('measurement').textContent.includes('1/4'));
 assert(get('raw').textContent.includes('fixture Gemini raw'));
 assert(!source.includes('api_key'));
 const restored={...task,reference:{text:'fixed fixture reference'},reference_draft:null,transcript:{text:'fixture Gemini raw'},measurement};
 await run('restoreTask('+JSON.stringify(restored)+')');
 assert(get('measurement').textContent.includes('25.0%'));
 checks.push('Explicit Gemini action sends only the current task and restores descriptive raw measurements without key entry');
 process.stdout.write(JSON.stringify({passed:checks.length,checks,constructed_fixtures:true,browser_visual_qa:false,model_calls:0}));
})().catch(error=>{console.error(error.stack);process.exitCode=1});
