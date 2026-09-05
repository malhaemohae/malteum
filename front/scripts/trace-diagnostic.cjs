// Diagnostic only: leaves source records untouched; creates and closes its own TRACE runs.
// Output contains timing/count metadata, never speech text or credentials.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const WebSocket = require('next/dist/compiled/ws');
const base = 'http://127.0.0.1:8000';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function get(resource) {
  const response = await fetch(base + '/api' + resource, {signal:AbortSignal.timeout(15000)});
  assert.equal(response.status,200); return response.json();
}
async function run(sourceId, limitSeconds) {
  const source = await get(`/sessions/${sourceId}`);
  const stored = await get(`/sessions/${sourceId}/events`);
  assert.ok(!stored.truncated,'select a source whose complete events fit this diagnostic');
  const response = await fetch(base+'/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'trace',source_session_id:sourceId,pack_version:source.pack_version})});
  assert.equal(response.status,201);const created=await response.json();
  const ws = new WebSocket(new URL(created.ws_url,base.replace('http:','ws:')));
  const received=[];let start=Date.now();
  ws.on('message',data=>{
    const message=JSON.parse(data.toString());
    if(message.t==='ping'){ws.send(JSON.stringify({t:'pong'}));return;}
    const meta={t:message.t,seq:message.seq,eventId:message.event_id,t_ms:message.t_ms,speaker:message.speaker,seconds:Number(((Date.now()-start)/1000).toFixed(2)),code:message.code};
    received.push(meta);
    console.log(JSON.stringify({sourceMode:source.mode,sourceId,...meta}));
  });
  await new Promise((resolve,reject)=>{ws.once('open',resolve);ws.once('error',reject);});
  start=Date.now(); ws.send(JSON.stringify({t:'hello',session_id:created.session_id,mode:'trace'}));
  let forcedEnd=false;
  try {
    for(let elapsed=0;elapsed<limitSeconds&&!received.some(message=>message.t==='ended');elapsed++) {
      await delay(1000);
      if((elapsed+1)%30===0) console.log(JSON.stringify({sourceId,waitingSeconds:elapsed+1,utterances:received.filter(message=>message.t==='utterance').length}));
    }
    if(!received.some(message=>message.t==='ended')) {
      forcedEnd=true;ws.send(JSON.stringify({t:'end'}));
      for(let count=0;count<100&&!received.some(message=>message.t==='ended');count++)await delay(100);
    }
  } finally {ws.close();}
  const result={sourceId,traceId:created.session_id,sourceMode:source.mode,sourceDurationMs:source.duration_ms,sourceEvents:stored.events.map(event=>({kind:event.kind,seq:event.seq_in_session,occurredAt:event.occurred_at,t_ms:event.utterance?.t_ms})),sourceUtterances:stored.events.filter(event=>event.kind==='utterance').length,received,forcedEnd};
  result.firstUtteranceSeconds=received.find(message=>message.t==='utterance')?.seconds??null;
  result.traceReportSummary=(await get(`/sessions/${created.session_id}/report`)).sections?.summary;
  result.sourceReportSummary=(await get(`/sessions/${sourceId}/report`)).sections?.summary;
  return result;
}
(async()=>{
  const [source,traceHistory]=process.argv.slice(2);
  assert.ok(source&&traceHistory,'Pass the verified original session and TRACE-history session IDs');
  const results=await Promise.all([run(source,285),run(traceHistory,25)]);
  const output=path.resolve(__dirname,'../qa-output/trace-diagnostic.json');
  fs.writeFileSync(output,JSON.stringify({verifiedAt:new Date().toISOString(),results},null,2));
  console.log(JSON.stringify({results:results.map(({sourceId,traceId,sourceMode,sourceUtterances,received,firstUtteranceSeconds,forcedEnd,sourceReportSummary,traceReportSummary})=>({sourceId,traceId,sourceMode,sourceUtterances,receivedCounts:received.reduce((counts,m)=>(counts[m.t]=(counts[m.t]??0)+1,counts),{}),firstUtteranceSeconds,forcedEnd,sourceReportSummary,traceReportSummary}))},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
