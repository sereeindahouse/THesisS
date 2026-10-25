// Execute actual render/click/append/request code with a controlled DOM.
// The JSON output is resolved by the real Python capability implementation.
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2],'utf8');
const fixture=JSON.parse(fs.readFileSync(0,'utf8'));
const script=source.match(/<script>([\s\S]*?)<\/script>/);assert(script);
new vm.Script(script[1],{filename:'actual-demo-inline-script.js'});
function between(start,end){const left=source.indexOf(start),right=source.indexOf(end,left+start.length);
  assert(left>=0&&right>left,`Missing product source section ${start}`);return source.slice(left,right);}
class Element{
  constructor(tag='',text='',cls=''){this.tag=tag;this.textContent=text??'';this.className=cls;
    this.children=[];this.dataset={};this.handlers=new Map();this.value='';this.checked=false;
    this.disabled=false;this.hidden=false;this.style={};this.scrollHeight=40;}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=[...items];}
  setAttribute(key,value){this[key]=value;}
  addEventListener(event,handler){this.handlers.set(event,handler);}
  click(){this.handlers.get('click')?.();}
  requestSubmit(){this.handlers.get('submit')?.({preventDefault(){}});}
  remove(){}
}
const elements=new Map(),calls=[];
function $(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);}
const context=vm.createContext({$,console,Set,Map,Array,Number,String,Error,URL,fixture,
  node:(tag,text,cls)=>new Element(tag,text,cls),
  clearCorrection(){},clearSpeech(){},refreshVoiceControls(){},scrollChat(){},
  renderTeacherCards(){return null;},renderRelatedSources(){return null;},compactSourceList(){return new Element('ul');},
  setTimeout(){return {};},clearTimeout(){},
  api(path,body){calls.push({path,body});return path==='/api/route'?new Promise(()=>{}):Promise.resolve({removed:1});}
});
vm.runInContext(`
  let routeBusy=false,voiceBusy=false,micStarting=false,micRecorder=null,
      pendingClarification=fixture.pending??null,currentTranscription={id:'synthetic-audio'},
      chatSequence=0,routeGeneration=0,voiceGeneration=0,latestRoute=null;
  const chatTurns=[],ownedClarificationIds=new Set();
`,context);
vm.runInContext(between('function refreshClarificationHint()', '$('+'"clearClarification").addEventListener'),context);
vm.runInContext(between('function sizeComposer()', 'function compactSourceList'),context);
vm.runInContext(between('function appendTurn(', 'function hasSpokenReply'),context);
vm.runInContext(between('function hasSpokenReply(', 'function speakTurn'),context);
vm.runInContext(between('function submitFollowup(', 'function renderRelatedSources'),context);
vm.runInContext(between('function renderTurn(', 'async function askTurn'),context);
vm.runInContext(between('async function askTurn(', '$('+'"routeQuery").addEventListener("keydown"'),context);
$('routeDraft').checked=fixture.checkedDraft??false;
if(fixture.busy)vm.runInContext(fixture.busy==='recording'?"micRecorder={state:'recording'}":fixture.busy+'=true',context);
const turn={query:fixture.result.query,draft:fixture.turnDraft??false,result:null,
  body:new Element('div'),element:new Element('article'),userElement:new Element('div')};
context.turn=turn;
vm.runInContext('renderTurn(turn,fixture.result)',context);
function descendants(element){return [element,...element.children.filter(e=>e instanceof Element).flatMap(descendants)];}
const buttons=descendants(turn.body).filter(e=>e.tag==='button'&&e.dataset.followupQuery!==undefined);
const displayed=buttons.map(button=>({label:button.textContent,query:button.dataset.followupQuery}));
const index=fixture.selectedIndex??0;assert(buttons[index],`Missing rendered option ${index}`);
buttons[index].click();
const output={buttons:displayed,calls,pending:vm.runInContext('pendingClarification',context),
  currentTranscription:vm.runInContext('currentTranscription',context),
  routeStatus:$('routeStatus').textContent,composer:$('routeQuery').value,
  submitted:vm.runInContext('chatTurns.map(t=>({query:t.query,draft:t.draft,clarification:t.clarification,transcriptionId:t.transcriptionId}))',context),
  actual_render_and_click_executed:true,network_calls:0,model_calls:0};
process.stdout.write(JSON.stringify(output));
