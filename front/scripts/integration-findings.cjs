const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const base=process.env.QA_BASE_URL||'http://127.0.0.1:3000';
const WebSocket=require('next/dist/compiled/ws');
const backend='ws://127.0.0.1:8000/ws';const output=path.resolve(__dirname,'../qa-output');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function waitFor(messages,predicate){const deadline=Date.now()+15000;while(!messages.some(predicate)&&Date.now()<deadline)await delay(50);assert.ok(messages.some(predicate),'server response timeout: '+messages.map(value=>value.t).join(','));}
async function numeric(lines){
  const response=await fetch(base+'/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'text',pack_version:'DEP-2026.08-v6',product_code:'ICBC-KRW-TD',customer_profile:{type:'general',tags:['frontend-qa']}})});
  assert.equal(response.status,201);const created=await response.json();const messages=[];
  const ws=new WebSocket(backend);
  ws.addEventListener('message',event=>{const value=JSON.parse(event.data);if(value.t==='ping')ws.send(JSON.stringify({t:'pong'}));else messages.push(value);});
  await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
  try{
    ws.send(JSON.stringify({t:'hello',session_id:created.session_id,mode:'text'}));await waitFor(messages,value=>value.t==='ready');
    for(const text of lines){ws.send(JSON.stringify({t:'text_utterance',text,speaker:'teller'}));await delay(500);}
    await delay(4500);
    ws.send(JSON.stringify({t:'end'}));await waitFor(messages,value=>value.t==='ended');
    return {sessionId:created.session_id,lines,numericAlert:messages.some(value=>value.t==='alert'&&value.alert_type==='number_mismatch'),messages};
  }finally{ws.close();}
}
(async()=>{
  const combined=await numeric(['받으시는 이자 수익에는 과세가 되는데요, 세율은 14%입니다.']);
  const split=await numeric(['받으시는 이자 수익에는 과세가 되는데요.','세율은 14%입니다.']);
  const voice=JSON.parse(fs.readFileSync(path.join(output,'voice-qa.json'),'utf8'));
  const stored=await(await fetch(`${base}/api/sessions/${voice.sessionId}/events`)).json();
  const endIndex=stored.events.findIndex(value=>value.kind==='session_ended');
  const late=endIndex<0?[]:stored.events.slice(endIndex+1);
  const failures=[];
  if(combined.numericAlert&&!split.numericAlert)failures.push('Numeric alert is lost when the same speech is split into two utterances.');
  if(late.length)failures.push(`${late.length} persisted events arrived after session_ended.`);
  const result={verified_at:new Date().toISOString(),combined,split,voiceSession:voice.sessionId,endEvent:stored.events[endIndex],lateEvents:late,failures};
  fs.writeFileSync(path.join(output,'integration-findings.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({combinedAlert:combined.numericAlert,splitAlert:split.numericAlert,lateEvents:late.length,failures},null,2));
  if(failures.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
