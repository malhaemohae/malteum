const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:900}});page.setDefaultTimeout(30000);
 const messages=[];let packets=0;let nonzero=0;let id;
 await page.addInitScript(()=>{navigator.mediaDevices.getUserMedia=async()=>{const ctx=new AudioContext();const source=ctx.createConstantSource();source.offset.value=0;const dest=ctx.createMediaStreamDestination();source.connect(dest);source.start();await ctx.resume();window.__quietContext=ctx;return dest.stream;};});
 page.on('dialog',dialog=>dialog.accept());page.on('response',async r=>{if(r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/sessions'&&r.status()===201)id=(await r.json()).session_id;});
 page.on('websocket',ws=>{ws.on('framereceived',e=>{if(typeof e.payload==='string')messages.push(JSON.parse(e.payload));});ws.on('framesent',e=>{if(Buffer.isBuffer(e.payload)){packets++;if(e.payload.subarray(4).some(byte=>byte!==0))nonzero++;}});});
 try{
  await page.goto('http://localhost:3000',{waitUntil:'networkidle'});await page.getByRole('button',{name:/상담 시작|시작하기|대시보드/}).first().click();await page.getByRole('button',{name:'상담 시작 →'}).click();
  await page.getByRole('button',{name:'● 녹음 시작'}).waitFor();await page.waitForTimeout(8000);
  const before={packets,utterances:messages.filter(m=>m.t==='utterance').length};assert.equal(packets,0);
  await page.getByRole('button',{name:'● 녹음 시작'}).click();await page.getByRole('button',{name:'이어서 녹음 시작',exact:true}).click();await page.getByRole('button',{name:'■ 녹음 중지'}).waitFor();await page.waitForTimeout(32000);
  await page.getByRole('button',{name:'■ 녹음 중지'}).click();await page.waitForTimeout(3000);
  const result={id,before,silence:{packets,nonzero,utterances:messages.filter(m=>m.t==='utterance').map(m=>({text:m.text,t_ms:m.t_ms}))},errors:messages.filter(m=>m.t==='error')};
  await page.getByRole('button',{name:'상담 종료',exact:true}).click();await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor();
  fs.mkdirSync(path.resolve(__dirname,'../qa-output'),{recursive:true});fs.writeFileSync(path.resolve(__dirname,'../qa-output/live-silence-diagnostic.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 }finally{await browser.close();if(id){const detail=await(await fetch(`http://127.0.0.1:8000/api/sessions/${id}`)).json();if(detail.status==='running')await new Promise(resolve=>{const ws=new WebSocket('ws://127.0.0.1:8000/ws');const timer=setTimeout(()=>{ws.close();resolve()},10000);ws.onopen=()=>ws.send(JSON.stringify({t:'hello',session_id:id,mode:'live'}));ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.t==='ready')ws.send(JSON.stringify({t:'end'}));if(m.t==='ping')ws.send(JSON.stringify({t:'pong'}));if(m.t==='ended'){clearTimeout(timer);ws.close();resolve()}};ws.onerror=()=>{clearTimeout(timer);resolve()};});}}
})().catch(e=>{console.error(e);process.exitCode=1});
