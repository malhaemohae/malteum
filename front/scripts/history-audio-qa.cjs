const assert=require('node:assert/strict');const path=require('node:path');const fs=require('node:fs');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const {allSizes,failures}=require('./workspace-qa.cjs');
const sourceId='FIXT-SESS-0A';const base='http://localhost:3000';const api='http://127.0.0.1:8000/api';
const created=[];const errors=[];let browser;
async function get(url){const response=await fetch(api+url);assert.equal(response.status,200,url);return response.json();}
async function events(id){const result=[];let cursor=0;for(;;){const page=await get(`/sessions/${id}/events?from_seq=${cursor}`);for(const event of page.events)if(!result.some(row=>row.event_id===event.event_id))result.push(event);if(!page.truncated)return result;const next=Math.max(...page.events.map(row=>row.seq_in_session));assert.ok(next>cursor);cursor=next;}}
async function history(page,id,mode){
 await page.getByRole('navigation',{name:'주 메뉴'}).getByRole('button',{name:'이력',exact:true}).click();
 await page.getByLabel('이력 입력 방식').selectOption(mode);
 await page.waitForFunction(()=>document.querySelector('[data-workspace="history"] .wb-heading button')?.disabled===false&&document.querySelector('[data-session-id]'));
 const row=page.locator(`[data-session-id="${id}"]`).locator('..');
 for(let i=0;i<60;i++){if(await row.isVisible())return row;const next=page.getByLabel('세션 이력 다음 페이지');if(await next.isEnabled()){await next.click();await page.waitForTimeout(150);}else await page.waitForTimeout(100);}
 throw new Error('history row not found');
}
(async()=>{
 const before=await events(sourceId);assert.equal(before.find(row=>row.kind==='session_started').session_started.preset_id,'preset-dep-a');
 const speech=before.filter(row=>row.kind==='utterance');
 const manifest=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../public/replay/preset-dep-a/manifest.json'),'utf8'));
 browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1440,height:900}});const page=await context.newPage();page.setDefaultTimeout(45000);
 page.on('dialog',dialog=>dialog.accept());page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(()=>{
  window.__voiceStarts=[];window.__voiceStops=0;window.__voiceGains=[];
  const gain=AudioContext.prototype.createGain;AudioContext.prototype.createGain=function(){const node=gain.call(this);window.__voiceGains.push(node);return node;};
  const create=AudioContext.prototype.createBufferSource;AudioContext.prototype.createBufferSource=function(){const source=create.call(this);const start=source.start.bind(source);const stop=source.stop.bind(source);const context=this;
   source.start=(when,offset,duration)=>{window.__voiceStarts.push({offset,state:context.state,loader:!!document.querySelector('[data-trace-start]'),text:[...document.querySelectorAll('.wb-chat-rows .wb-chat-text')].map(el=>el.textContent).join(' ')});return start(when,offset,duration);};
   source.stop=(...args)=>{window.__voiceStops++;return stop(...args)};return source;};
 });
 const posts=[];page.on('request',request=>{if(request.method()==='POST'&&new URL(request.url()).pathname==='/api/sessions')posts.push(request.postDataJSON());});
 page.on('response',async response=>{if(response.request().method()==='POST'&&new URL(response.url()).pathname==='/api/sessions'&&response.status()===201)created.push((await response.json()).session_id);});
 for(let cycle=0;cycle<2;cycle++){
  await page.goto(base,{waitUntil:'networkidle'});await page.getByRole('button',{name:/상담 시작|시작하기|대시보드/}).first().click();
  if(cycle===0)assert.equal(await page.evaluate(()=>Object.keys(localStorage).filter(key=>key.startsWith('malteum.replay-preset.')).length),0);
  const row=await history(page,cycle===0?sourceId:created[0],cycle===0?'replay':'trace');await row.getByRole('button',{name:'TRACE 재생',exact:true}).click();
  await page.waitForFunction(()=>window.__voiceStarts.length>0);
  let starts=await page.evaluate(()=>window.__voiceStarts);assert.equal(starts[0].state,'running');assert.equal(starts[0].offset,manifest.cues[0].start);assert.equal(starts[0].loader,false);assert.ok(starts[0].text.includes(speech[0].utterance.text));
  assert.equal(posts[cycle].source_session_id,sourceId);assert.equal(posts[cycle].mode,'trace');
  await page.getByRole('button',{name:'소리 끄기',exact:true}).click();assert.equal(await page.evaluate(()=>window.__voiceGains.at(-1).gain.value),0);
  await page.getByRole('button',{name:'소리 켜기',exact:true}).click();assert.equal(await page.evaluate(()=>window.__voiceGains.at(-1).gain.value),1);
  if(cycle===0){await allSizes(page,'history-trace-audio');await page.waitForFunction(()=>window.__voiceStarts.length>=2);starts=await page.evaluate(()=>window.__voiceStarts);assert.equal(starts[1].offset,manifest.cues[1].start);assert.ok(starts[1].text.includes(speech[1].utterance.text));}
  await page.getByRole('button',{name:'재생 종료',exact:true}).click();await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor();assert.equal((await get(`/sessions/${created[cycle]}`)).status,'ended');
  assert.ok(await page.evaluate(()=>window.__voiceStops>0));console.log('PASS existing history audio:',cycle===0?'DB preset, no local mapping':'repeat TRACE after reload');
 }
 assert.deepEqual(await events(sourceId),before,'source DB event history is unchanged');assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);
 fs.writeFileSync(path.resolve(__dirname,'../qa-output/history-audio-qa.json'),JSON.stringify({sourceId,created,checks:['DB event preset identity','fresh browser','actual TRACE captions before original WAV audio','first two turns','mute/unmute','stop on end','repeat after reload','source log unchanged','10 viewports'],errors,failures},null,2));
})().catch(error=>{console.error(error);process.exitCode=1}).finally(async()=>{
 await browser?.close();
 for(const id of created){try{if((await get(`/sessions/${id}`)).status!=='running')continue;await new Promise(resolve=>{const ws=new WebSocket('ws://127.0.0.1:8000/ws');const timer=setTimeout(()=>{ws.close();resolve()},12000);ws.onopen=()=>ws.send(JSON.stringify({t:'hello',session_id:id,mode:'trace'}));ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.t==='ready')ws.send(JSON.stringify({t:'end'}));if(m.t==='ping')ws.send(JSON.stringify({t:'pong'}));if(m.t==='ended'){clearTimeout(timer);ws.close();resolve()}};ws.onerror=()=>{clearTimeout(timer);resolve()};});}catch{}}
});
