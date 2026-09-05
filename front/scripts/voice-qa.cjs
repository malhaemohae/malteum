// Real browser microphone -> PCM -> Docker diarization -> configured STT -> judgement -> DB.
// Chromium substitutes only the microphone device with the repository's synthetic scenario audio.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const output = path.resolve(__dirname,'../qa-output');
const base = process.env.QA_BASE_URL || 'http://127.0.0.1:3000';
(async () => {
  const audio = path.resolve(__dirname,'../../assets/scenarios/preset-dep-a/audio.wav');
  assert.ok(fs.existsSync(audio));
  const health = await (await fetch(base+'/api/health')).json();
  assert.equal(health.checks.db,'ok'); assert.equal(health.checks.stt,'ok'); assert.equal(health.checks.llm,'ok');
  const browser = await chromium.launch({headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream',`--use-file-for-fake-audio-capture=${audio}`]});
  const page = await browser.newPage({viewport:{width:1440,height:900},permissions:['microphone']});
  page.setDefaultTimeout(30000);
  const messages=[]; const errors=[]; let frames=0;
  page.on('pageerror',error=>errors.push(error.message));
  page.on('websocket',ws=>{
    ws.on('framesent',event=>{if(Buffer.isBuffer(event.payload)){assert.equal(event.payload.length,3204);frames++;}});
    ws.on('framereceived',event=>{if(typeof event.payload==='string'){try{messages.push(JSON.parse(event.payload));}catch{}}});
  });
  try {
    await page.goto(base);
    await page.getByRole('button',{name:'상담 시작하기',exact:false}).first().click();
    await page.getByRole('button',{name:'상담 시작 →'}).click();
    await page.getByRole('button',{name:'● 녹음 시작'}).click();
    await page.getByRole('button',{name:'이어서 녹음 시작',exact:true}).click();
    const deadline=Date.now()+90000;
    while (Date.now()<deadline && !messages.some(value=>value.t==='alert'&&value.alert_type==='number_mismatch')) {
      await page.waitForTimeout(500);
      if(messages.some(value=>value.t==='error')) break;
    }
    await page.getByRole('button',{name:'■ 녹음 중지'}).click();
    await page.screenshot({path:path.join(output,'voice-live.png')});
    await page.getByRole('button',{name:'상담 종료',exact:true}).click();
    await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor({timeout:60000});
    const ended=messages.findLast(value=>value.t==='ended');
    assert.ok(ended,'real server must complete the recording session');
    await page.waitForTimeout(4000); // Detect buffered STT results written after the end acknowledgement.
    const events=await(await fetch(`${base}/api/sessions/${ended.session_id}/events`)).json();
    const report=await(await fetch(`${base}/api/sessions/${ended.session_id}/report`)).json();
    const semanticFailures=[];
    if (!messages.some(value=>value.t==='alert'&&value.alert_type==='number_mismatch')) semanticFailures.push('Scenario tax rate 14% did not produce the required numeric mismatch alert.');
    const endIndex=events.events.findIndex(value=>value.kind==='session_ended');
    if (endIndex<0 || endIndex!==events.events.length-1) semanticFailures.push('Stored events arrived after session_ended; the report was acknowledged before STT drained.');
    const result={health,frames,sessionId:ended.session_id,messages,events,report,errors,semanticFailures};
    fs.writeFileSync(path.join(output,'voice-qa.json'),JSON.stringify(result,null,2));
    assert.ok(frames>100,'must transmit actual audio for >10s');
    assert.ok(messages.some(value=>value.t==='utterance'&&String(value.text).length>8),'configured STT must produce real speech text');
    assert.ok(messages.some(value=>value.t==='verdict'),'speech must reach the judgement engine');
    assert.ok(events.events.some(value=>value.kind==='utterance'),'speech must be persisted');
    assert.equal(report.session_id,ended.session_id); assert.deepEqual(errors,[]);
    assert.ok(!messages.some(value=>value.t==='error'),'no hidden STT/provider errors');
    console.log(JSON.stringify({sessionId:ended.session_id,frames,utterances:messages.filter(value=>value.t==='utterance').length,verdicts:messages.filter(value=>value.t==='verdict').length,alerts:messages.filter(value=>value.t==='alert').length,persistedEvents:events.events.length},null,2));
    assert.deepEqual(semanticFailures,[],'end-to-end acceptance conditions, not just transport');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
