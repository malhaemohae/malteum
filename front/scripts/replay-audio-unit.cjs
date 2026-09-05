const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const ts=require('typescript');
require.extensions['.ts']=(module,file)=>module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,file);
const {ReplayAudio,findReplayCue}=require('../lib/replay-audio.ts');
const manifest=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../public/replay/preset-dep-a/manifest.json'),'utf8'));
for(const preset of ['preset-dep-a','preset-loan-b']){
 const data=JSON.parse(fs.readFileSync(path.resolve(__dirname,`../public/replay/${preset}/manifest.json`),'utf8'));
 for(let i=0;i<data.cues.length;i++){assert.equal(findReplayCue(data.cues[i].text,data.cues,i-1),i);assert.equal(findReplayCue(data.cues[i].spokenText,data.cues,i-1),i);}
}
assert.equal(findReplayCue('안녕하세요',manifest.cues,-1),0);
assert.equal(findReplayCue('작년에 넣어둔 정기예금이 있는데 만기가',manifest.cues,0),0);
assert.equal(findReplayCue('네',manifest.cues,0),-1);
assert.equal(findReplayCue('등록되지 않은 다른 상담 내용',manifest.cues,0),-1);
assert.equal(findReplayCue(manifest.cues[0].text,manifest.cues,4),-1);
const order=[];const sources=[];let ctx;
class Context {
 constructor(){ctx=this;this.state='running';this.destination={};}
 createGain(){return this.gain={gain:{value:1},connect(){}};}
 resume(){return Promise.resolve();} close(){this.state='closed';return Promise.resolve();}
 decodeAudioData(){return Promise.resolve({duration:manifest.duration});}
 createBufferSource(){const source={connect(){},disconnect(){},start(when,offset,duration){order.push('audio');source.offset=offset;source.duration=duration;},stop(){source.stopped=true;},onended:null};sources.push(source);return source;}
}
global.AudioContext=Context;
global.fetch=async url=>url.endsWith('manifest.json')?{ok:true,json:async()=>manifest}:{ok:true,arrayBuffer:async()=>new ArrayBuffer(2)};
const speech=index=>({t:'utterance',text:manifest.cues[index].text});
(async()=>{
 const states=[];const player=new ReplayAudio(value=>states.push(value));await player.prepare('preset-dep-a',manifest.packVersion);
 await player.present(speech(0),()=>order.push('caption'));
 assert.deepEqual(order,['caption','audio']);assert.equal(sources[0].offset,manifest.cues[0].start);
 await player.present({t:'utterance',text:'작년에 넣어 둔 정기예금이 있는데'},()=>{});assert.equal(sources.length,1,'split STT messages do not restart the whole TTS turn');
 let shown=false;const pending=player.present(speech(1),()=>{shown=true;});await Promise.resolve();assert.equal(shown,false,'next turn waits for the previous voice');
 sources[0].onended();await pending;assert.equal(shown,true);assert.equal(sources.length,2);
 await player.toggle();assert.equal(ctx.gain.gain.value,0);await player.toggle();assert.equal(ctx.gain.gain.value,1);
 const next=player.present(speech(2),()=>order.push('kept-on-stop'));await Promise.resolve();player.stop();await next;
 assert.ok(order.includes('kept-on-stop'),'stopping audio never discards a server utterance');assert.equal(sources[1].stopped,true);
 player.setVisible(false);await player.present(speech(3),()=>{});assert.equal(sources.length,2,'background screen does not play audio');
 player.setVisible(true);player.restoreTranscript(manifest.cues.slice(0,5).map(c=>c.text));await player.present(speech(4),()=>{});assert.equal(sources.length,2,'reconnect does not reread restored speech');
 await player.present(speech(5),()=>{});assert.equal(sources.length,3);player.dispose();assert.equal(ctx.state,'closed');
 const deviceLost=new ReplayAudio(()=>{});await deviceLost.prepare('preset-dep-a',manifest.packVersion);ctx.createBufferSource=()=>{throw new Error('device gone')};let preserved=false;await deviceLost.present(speech(0),()=>{preserved=true});assert.equal(preserved,true,'audio device errors must not swallow the server caption');deviceLost.dispose();
 const originalFetch=fetch;global.fetch=async()=>({ok:false});const failed=[];const unavailable=new ReplayAudio(value=>failed.push(value));await unavailable.prepare('preset-dep-a',manifest.packVersion);unavailable.stop();assert.equal(failed.at(-1).status,'unavailable');unavailable.dispose();global.fetch=originalFetch;
 const blocked=[];class Blocked extends Context{constructor(){super();this.state='suspended';}}global.AudioContext=Blocked;
 const locked=new ReplayAudio(value=>blocked.push(value));await locked.prepare('preset-dep-a',manifest.packVersion);const count=sources.length;await locked.present(speech(0),()=>{});assert.equal(sources.length,count);assert.equal(blocked.at(-1).status,'blocked');ctx.resume=async()=>{ctx.state='running'};await locked.toggle();assert.equal(blocked.at(-1).status,'ready');locked.dispose();
 console.log('PASS: original 32 TTS turns, received captions before audio, split-STT deduplication, no overlapping voices, mute, background/stop/dispose, reconnect, missing assets and autoplay block');
})().catch(error=>{console.error(error);process.exitCode=1});
