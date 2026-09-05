const assert=require('node:assert/strict');const path=require('node:path');const fs=require('node:fs');const crypto=require('node:crypto');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const {allSizes,failures}=require('./workspace-qa.cjs');
const created=[];const errors=[];const checks=[];let browser;
const base='http://localhost:3000';const api='http://127.0.0.1:8000/api';
async function get(url){const response=await fetch(api+url);assert.equal(response.status,200,url);return response.json();}
(async()=>{
 browser=await chromium.launch({headless:true});
 for(const [preset,version] of [['preset-dep-a','DEP-2026.08-v4'],['preset-loan-b','LOAN-2026.08-v5']]){
  const manifest=JSON.parse(fs.readFileSync(path.resolve(__dirname,`../public/replay/${preset}/manifest.json`),'utf8'));
  const asset=await fetch(base+manifest.audioUrl);assert.equal(asset.status,200);assert.equal(crypto.createHash('sha256').update(Buffer.from(await asset.arrayBuffer())).digest('hex'),manifest.sha256);
  const context=await browser.newContext({viewport:{width:1440,height:900}});const page=await context.newPage();page.setDefaultTimeout(60000);page.on('dialog',dialog=>dialog.accept());page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{
   window.__audioStarts=[];window.__audioStops=0;window.__audioGains=[];
   const gain=AudioContext.prototype.createGain;AudioContext.prototype.createGain=function(){const node=gain.call(this);window.__audioGains.push(node);return node;};
   const create=AudioContext.prototype.createBufferSource;AudioContext.prototype.createBufferSource=function(){
    const source=create.call(this);const start=source.start.bind(source);const stop=source.stop.bind(source);const context=this;
    source.start=(when,offset,duration)=>{const pcm=source.buffer.getChannelData(0);const rate=source.buffer.sampleRate;let sum=0;let count=0;for(let i=Math.floor(offset*rate);i<Math.min(pcm.length,Math.floor((offset+1)*rate));i++){sum+=pcm[i]*pcm[i];count++;}window.__audioStarts.push({offset,duration,context:context.state,rms:Math.sqrt(sum/Math.max(1,count)),text:[...document.querySelectorAll('.wb-chat-rows .wb-chat-text')].map(el=>el.textContent).join(' ')});return start(when,offset,duration);};
    source.stop=(...args)=>{window.__audioStops++;return stop(...args);};return source;
   };
  });
  page.on('response',async response=>{if(response.request().method()==='POST'&&new URL(response.url()).pathname==='/api/sessions'&&response.status()===201)created.push((await response.json()).session_id)});
  const messages=[];page.on('websocket',ws=>ws.on('framereceived',event=>{if(typeof event.payload==='string')messages.push(JSON.parse(event.payload));}));
  await page.goto(base,{waitUntil:'networkidle'});await page.getByRole('button',{name:/상담 시작|시작하기|대시보드/}).first().click();
  await page.getByLabel('상품·규정 팩').selectOption(version);await page.getByLabel('입력 방식',{exact:true}).selectOption('replay');await page.getByRole('button',{name:'상담 시작 →',exact:true}).click();
  await page.waitForFunction(()=>window.__audioStarts.length>0);
  let starts=await page.evaluate(()=>window.__audioStarts);assert.equal(starts[0].context,'running');assert.ok(starts[0].rms>.0001,'decoded original audio contains non-silent samples');assert.equal(starts[0].offset,manifest.cues[0].start);
  assert.ok(messages.some(m=>m.t==='utterance'&&starts[0].text.includes(m.text)),'actual server text is visible when its voice starts, not script substitution');
  await page.getByRole('button',{name:'소리 끄기',exact:true}).click();assert.equal(await page.evaluate(()=>window.__audioGains.at(-1).gain.value),0);
  await page.getByRole('button',{name:'소리 켜기',exact:true}).click();assert.equal(await page.evaluate(()=>window.__audioGains.at(-1).gain.value),1);
  if(preset==='preset-dep-a')await allSizes(page,'replay-audio-controls');
  await page.waitForFunction(()=>window.__audioStarts.length>=2);
  starts=await page.evaluate(()=>window.__audioStarts);assert.equal(starts[1].offset,manifest.cues[1].start,'second speaker uses the second original turn');
  await page.getByRole('button',{name:'상담 종료',exact:true}).click();await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor();
  assert.equal((await get(`/sessions/${created.at(-1)}`)).status,'ended');
  const after=await page.evaluate(()=>window.__audioStarts.length);await page.waitForTimeout(700);assert.equal(await page.evaluate(()=>window.__audioStarts.length),after,'no sound starts after ending');
  checks.push({preset,firstTwoOffsets:starts.slice(0,2).map(value=>value.offset),nonSilent:true,serverCaptionAtStart:true,mute:true,ended:true});
  await context.close();console.log('PASS real REPLAY audio:',preset);
 }
 assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);
 fs.writeFileSync(path.resolve(__dirname,'../qa-output/replay-audio-qa.json'),JSON.stringify({created,checks,errors,failures},null,2));
})().catch(error=>{console.error(error);process.exitCode=1}).finally(async()=>{
 await browser?.close();
 for(const id of created){try{if((await get(`/sessions/${id}`)).status!=='running')continue;await new Promise(resolve=>{const ws=new WebSocket('ws://127.0.0.1:8000/ws');const timer=setTimeout(()=>{ws.close();resolve()},12000);ws.onopen=()=>ws.send(JSON.stringify({t:'hello',session_id:id,mode:'replay'}));ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.t==='ready')ws.send(JSON.stringify({t:'end'}));if(m.t==='ping')ws.send(JSON.stringify({t:'pong'}));if(m.t==='ended'){clearTimeout(timer);ws.close();resolve()}};ws.onerror=()=>{clearTimeout(timer);resolve()};});}catch{}}
});
