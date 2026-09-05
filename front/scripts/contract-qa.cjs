const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,filename);
const {newLiveSession,reduceServer,evidenceForItem} = require('../lib/workspace-model.ts');
const {apiUrl} = require('../lib/api.ts');
const messages = JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../back/contracts/fixtures/ws_messages.json'),'utf8'));
const ready=messages.find(m=>m.t==='ready');
let state=reduceServer(newLiveSession(ready.session_id,'/ws','replay',ready.pack_version),ready);
assert.equal(state.items.length,6); assert.equal(state.progress,undefined,'do not calculate progress from checklist');
const verdict=messages.find(m=>m.t==='verdict'&&m.axis==='omission');
state=reduceServer(state,verdict);assert.equal(state.items.find(i=>i.code===verdict.item_code).state,verdict.state);
const corrected={...verdict,event_id:'QA-HIGH-VER',seq:99,ver:3,state:'partial'};
state=reduceServer(state,corrected);
state=reduceServer(state,{...verdict,event_id:'QA-OLDER',seq:100,ver:2,state:'met'});
assert.equal(state.items.find(i=>i.code===verdict.item_code).state,'partial');
state=reduceServer(state,{...corrected,event_id:'QA-HIGHER-OUT-OF-ORDER',seq:98,ver:4,state:'met'});
assert.equal(state.items.find(i=>i.code===verdict.item_code).state,'met','highest item version wins even when sequence arrives out of order');
state=reduceServer(state,{...verdict,event_id:'QA-OTHER-AXIS',seq:101,axis:'commission',ver:5,state:'violated'});
assert.equal(state.items.find(i=>i.code===verdict.item_code).state,'met','commission must not overwrite omission');
state=reduceServer(newLiveSession(ready.session_id,'/ws','replay',ready.pack_version),ready);
const risk=messages.find(m=>m.t==='alert'&&m.alert_type==='risk_signal');
state=reduceServer(state,risk);
state=reduceServer(state,{...messages.find(m=>m.t==='assist'&&m.assist_type==='rephrase'),seq:30});
assert.equal(state.interventions[0].kind,'risk_signal','lower priority must not overwrite risk');
const unsupportedAnswer={...messages.find(m=>m.t==='assist'&&m.assist_type==='answer'),seq:31,evidence_ref:undefined};
state=reduceServer(state,unsupportedAnswer);
assert.ok(!state.query.answer.includes(unsupportedAnswer.text));
const progress=messages.find(m=>m.t==='progress');state=reduceServer(state,{...progress,seq:32});
assert.equal(state.progress.total,progress.items_total);assert.equal(state.progress.density,progress.term_density);
const before=state.items; state=reduceServer(state,{...messages.find(m=>m.t==='error'),seq:33});assert.deepEqual(state.items,before);assert.equal(state.status,'connected','STT error must not disconnect TEXT fallback');
assert.equal(apiUrl('/api/sessions/one/report.pdf'),'/api/sessions/one/report.pdf');
assert.equal(apiUrl('/sessions/one/report.pdf'),'/api/sessions/one/report.pdf');
state=reduceServer(state,{...risk,event_id:'QA-ACK-RISK',seq:34,acknowledged:true});
assert.ok(!state.interventions.some(i=>i.kind==='risk_signal'),'acknowledged alert must not reappear');
const {reportHtml}=require('../lib/report-print.ts');
assert.ok(reportHtml({session_id:'empty',pack_version:'test',generated_at:''}).includes('기록 없음'),'partial reports must still export safely');
const printed=reportHtml({session_id:'qa',pack_version:'test',generated_at:'',sections:{omission:[{name:'<script>bad</script>',state:'met'}],risk_signals:[{message:'확인 기록'}]}});
assert.ok(printed.includes('&lt;script&gt;bad&lt;/script&gt;')&&!printed.includes('<script>bad'),'server report text must be escaped');
assert.ok(printed.includes('확인 기록'),'print includes all sections regardless of active tab');
const pack=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../back/contracts/fixtures/rulepack_DEP-2026.08-v4.json'),'utf8'));
const item=pack.items.find(i=>i.evidence);const evidence=evidenceForItem(pack,item);
assert.equal(evidence.span,item.evidence.span);assert.equal(evidence.page,item.evidence.page);
console.log('PASS: contract fixture states, independent axes, out-of-order versions, priority, grounding, server progress, STT fallback, evidence and PDF URLs.');

// Exercise the real audio packetizer with deterministic Web Audio fakes, including a 48 kHz fallback.
const {Pcm16Capture}=require('../lib/audio.ts');
(async()=>{
  for (const rate of [16000,48000,44100]) {
    let processor;let stopped=0;
    const track={stop:()=>stopped++};
    Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[track]})}}});
    globalThis.window={AudioContext:class {constructor(){this.sampleRate=rate;this.state='running';this.destination={};} createMediaStreamSource(){return{connect(){},disconnect(){}};}createScriptProcessor(size){assert.equal(size,4096);processor={connect(){},disconnect(){}};return processor;}resume(){return Promise.resolve();}close(){this.state='closed';return Promise.resolve();}}};
    const frames=[];const capture=new Pcm16Capture(17);await capture.start((frame)=>frames.push(frame));
    for(let n=0;n<Math.ceil(rate/4096);n++)processor.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(4096).fill(.5)}});
    assert.ok(frames.length>=9&&frames.length<=11,`one second at ${rate} must yield ~10 100ms frames, got ${frames.length}`);
    frames.forEach((frame,i)=>{assert.equal(frame.byteLength,3204);const view=new DataView(frame);assert.equal(view.getUint32(0,false),17+i);assert.equal(view.getInt16(4,true),16383);});
    capture.stop();assert.equal(stopped,1);
  }
  console.log('PASS: microphone PCM16 packet length, sequence, sample conversion, 16/44.1/48 kHz resampling, and track cleanup.');
})().catch(error=>{console.error(error);process.exitCode=1;});

(async()=>{
  const { malteumApi, findSessionEvent, setAdminToken } = require('../lib/api.ts');
  const originalFetch = global.fetch;
  try {
    let calls=[];
    global.fetch=async(url,init)=>{calls.push({url,init});return new Response(JSON.stringify({events:url.includes('from_seq=0')?[{event_id:'first',seq_in_session:10}]:[{event_id:'confirmed',seq_in_session:11,alert:{acknowledged:true}}],truncated:url.includes('from_seq=0')}),{headers:{'Content-Type':'application/json'}});};
    const found=await findSessionEvent('test','confirmed');
    assert.equal(found.alert.acknowledged,true); assert.equal(calls.length,2);
    assert.ok(calls[1].url.includes('from_seq=10'),'read the next server event page');
    setAdminToken('test-only-token'); calls=[];
    await malteumApi.packs(); await malteumApi.extraction('test');
    assert.equal(calls[0].init.headers.Authorization,undefined,'public reads never send admin credentials');
    assert.equal(calls[1].init.headers.Authorization,'Bearer test-only-token');
    console.log('PASS: event pagination and runtime-only, admin-path-scoped authentication.');
  } finally { global.fetch=originalFetch; setAdminToken(''); }
})().catch(error=>{console.error(error);process.exitCode=1;});
