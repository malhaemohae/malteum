const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const { allSizes, failures } = require('./workspace-qa.cjs');
const base='http://localhost:3000'; const api='http://127.0.0.1:8000/api';
// Already-created local QA records, not user consultations. Only NEW replay IDs
// may be ended by this test. The original events are snapshotted and compared.
const legacyId='01M1R7W2V0JHRQXB46E2WM8ZZT';
const sourceId='01M1R7VANZHAHTXC4B7X8P7495';
const created=[]; const errors=[]; let browser;
const checkLoading=process.env.QA_TRACE_LOADING==='1';
async function request(url){const response=await fetch(api+url);assert.equal(response.status,200,url);return response.json();}
async function history(page,id){
 await page.getByRole('navigation',{name:'주 메뉴'}).getByRole('button',{name:'이력',exact:true}).click();
 await page.getByLabel('이력 입력 방식').selectOption('trace');
 const row=page.locator(`[data-session-id="${id}"]`).locator('..');
 for(let i=0;i<60;i++){
  if(await row.isVisible())return row;
  const next=page.getByLabel('세션 이력 다음 페이지');
  if(await next.isEnabled()){await next.click();await page.waitForTimeout(150);} else await page.waitForTimeout(100);
 }
 throw new Error('TRACE row not found');
}
async function end(page){await page.getByRole('button',{name:'재생 종료',exact:true}).click();await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor();}
(async()=>{
 const before=await request(`/sessions/${sourceId}/events`); const legacyBefore=await request(`/sessions/${legacyId}/events`);
 browser=await chromium.launch({headless:true}); const context=await browser.newContext({viewport:{width:1440,height:900}}); const page=await context.newPage(); page.setDefaultTimeout(25000);
 page.on('dialog',dialog=>dialog.accept()); page.on('pageerror',error=>errors.push(error.message));
 const posts=[]; const frames=[];
 let releaseFirstUtterance; let gateNext=checkLoading;
 if(checkLoading)await page.routeWebSocket('**/ws',client=>{
  const server=client.connectToServer();
  if(!gateNext)return; gateNext=false;
  // Test-only delivery delay. Use the real backend messages unchanged and in
  // order; production replay timing is never changed by the frontend.
  const held=[]; let released=false; let holding=false;
  releaseFirstUtterance=()=>{released=true;for(const message of held)client.send(message);held.length=0;};
  server.onMessage(raw=>{
   const message=JSON.parse(raw.toString());
   if(message.t==='ping'||message.t==='ended'){client.send(raw);return;}
   if(message.t==='utterance')holding=true;
   if(holding&&!released)held.push(raw);else client.send(raw);
  });
 });
 page.on('request',req=>{if(req.method()==='POST'&&new URL(req.url()).pathname==='/api/sessions')posts.push(req.postDataJSON());});
 page.on('response',async response=>{if(response.request().method()==='POST'&&new URL(response.url()).pathname==='/api/sessions'&&response.status()===201)created.push((await response.json()).session_id)});
 page.on('websocket',ws=>ws.on('framereceived',event=>{if(typeof event.payload==='string')frames.push(JSON.parse(event.payload))}));
 await page.goto(base,{waitUntil:'networkidle'}); await page.getByRole('button',{name:/상담 시작|시작하기|대시보드/}).first().click();
 let row=await history(page,legacyId);
 assert.equal(await page.getByText('TRACE 이력이 아닌 원본 상담에서 재생해 주세요.',{exact:true}).count(),0);
 assert.equal(await row.getByRole('button',{name:'TRACE 재생',exact:true}).isEnabled(),true);
 await row.getByRole('button',{name:'TRACE 재생',exact:true}).click();
 const picker=page.getByRole('dialog',{name:'재생할 상담 선택',exact:true}); await picker.waitFor();
 await picker.locator('[data-trace-candidate]').first().waitFor();
 assert.equal(posts.length,0,'unresolved TRACE does not silently create a blank replay');
 await allSizes(page,'trace-source-picker');
 await page.getByLabel('재생할 상담 검색').fill(sourceId);
 const candidate=picker.locator(`[data-trace-candidate="${sourceId}"]`); await candidate.waitFor();
 const text=before.events.find(e=>e.kind==='utterance').utterance.text;
 assert.ok((await candidate.textContent()).includes(text),'preview comes from stored events');
 await candidate.locator('.wb-trace-preview').click();
 await page.getByRole('dialog',{name:'첫 발화',exact:true}).waitFor();
 assert.equal(await page.locator('dialog[open]').count(),1,'preview replaces the picker content without stacking dialogs');
 await allSizes(page,'trace-inline-preview');
 await page.getByRole('dialog',{name:'첫 발화',exact:true}).getByRole('button',{name:'이 상담 재생',exact:true}).click();
 if(checkLoading){
  await page.getByRole('heading',{name:'첫 발화를 불러오고 있습니다',exact:true}).waitFor();
  assert.equal(await page.locator('.wb-dashboard').count(),0,'no empty dashboard under the waiting screen');
  assert.equal(await page.getByRole('button',{name:'재생 중지',exact:true}).isEnabled(),true);
  await allSizes(page,'trace-first-utterance-loading');
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('.wb-trace-spinner').evaluate(el=>getComputedStyle(el).animationName),'none');
  await page.emulateMedia({reducedMotion:'no-preference'});
  assert.equal(await page.locator('[data-trace-start]').isVisible(),true,'waiting persists throughout delayed delivery');
  releaseFirstUtterance();
 }
 await page.waitForFunction(()=>document.querySelector('[data-workspace="playback"]')&&document.querySelector('[data-paged-list="상담 전사"]')?.textContent.includes('중도해지'));
 assert.equal(posts[0].source_session_id,sourceId);
 assert.ok(frames.some(m=>m.t==='utterance'&&m.text===text),'actual backend WS replays the original utterance');
 assert.equal(await page.locator('[data-trace-start]').count(),0,'the first final utterance removes the loading screen');
 await end(page); const firstTrace=created[0];assert.ok(firstTrace);
 assert.equal((await request(`/sessions/${firstTrace}`)).status,'ended');
 await page.reload({waitUntil:'networkidle'});await page.getByRole('button',{name:/상담 시작|시작하기|대시보드/}).first().click();
 if(checkLoading)gateNext=true;
 row=await history(page,firstTrace); await row.getByRole('button',{name:'TRACE 재생',exact:true}).click();
 if(checkLoading){
  await page.getByRole('heading',{name:'첫 발화를 불러오고 있습니다',exact:true}).waitFor();
  await page.getByRole('button',{name:'재생 중지',exact:true}).click();
  await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor();
  assert.equal((await request(`/sessions/${created[1]}`)).status,'ended','stopping before the first utterance is saved by the actual server');
 }else{
  await page.waitForFunction(()=>document.querySelector('[data-workspace="playback"]')&&document.querySelector('[data-paged-list="상담 전사"]')?.textContent.includes('중도해지'));
  await end(page);
 }
 assert.equal(await picker.count(),0,'new TRACE directly replays its exact source after reload');
 assert.equal(posts[1].source_session_id,sourceId,'TRACE of TRACE follows the original, not the empty replay record');
 assert.deepEqual(await request(`/sessions/${sourceId}/events`),before,'original event log unchanged');
 assert.deepEqual(await request(`/sessions/${legacyId}/events`),legacyBefore,'legacy TRACE unchanged, no inferred backfill');
 assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);
 fs.writeFileSync(path.resolve(__dirname,checkLoading?'../qa-output/trace-loading-qa.json':'../qa-output/trace-source-qa.json'),JSON.stringify({created,checks:['legacy TRACE enabled','no blank TRACE creation','actual stored preview and explicit selection','original backend WS replay','new TRACE repeat after reload','original events unchanged','10 responsive picker sizes',...(checkLoading?['real WS delivery delay: loader until first utterance','10 responsive loading sizes','reduced motion','stop before first utterance saved by server']:[])],errors,failures},null,2));
 console.log('PASS: real backend TRACE selection/replay/repeat after reload; original records unchanged; 10 viewports; new QA IDs:',created.join(', '));
})().catch(error=>{console.error(error);process.exitCode=1}).finally(async()=>{
 await browser?.close();
 // Only close test-created records after a failed browser action.
 for(const id of created){try{if((await request(`/sessions/${id}`)).status!=='running')continue;await new Promise(resolve=>{const ws=new WebSocket('ws://127.0.0.1:8000/ws');const timer=setTimeout(()=>{ws.close();resolve()},12000);ws.onopen=()=>ws.send(JSON.stringify({t:'hello',session_id:id,mode:'trace'}));ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.t==='ready')ws.send(JSON.stringify({t:'end'}));if(m.t==='ping')ws.send(JSON.stringify({t:'pong'}));if(m.t==='ended'){clearTimeout(timer);ws.close();resolve()}};ws.onerror=()=>{clearTimeout(timer);resolve()};});}catch{}}
});
