import type { ServerMessage } from './api';

export type ReplayCue={id:string;start:number;end:number;text:string;spokenText:string};
export type ReplayAudioState={enabled:boolean;status:'loading'|'ready'|'playing'|'blocked'|'unavailable';error?:string;cueId?:string};
type Manifest={presetId:string;packVersion:string;audioUrl:string;duration:number;cues:ReplayCue[]};
const normalize=(text:string)=>text.toLowerCase().replace(/디에스알/g,'dsr').replace(/[^a-z0-9가-힣]/g,'');

// 한 묶음으로 도착한 발화를 한 번에 쏟지 않고 이 간격으로 하나씩 올린다. 서버의 구간
// 단위 전사가 문장 세 개를 80ms 안에 한꺼번에 주므로, 그대로 얹으면 실시간 전사가
// 아니라 붙여넣기처럼 보인다
const REVEAL_GAP_MS=700;
// 재생 위치를 기다리는 상한. 음원이 없거나 짧아 위치가 끝내 안 지나가도 전사를
// 인질로 잡지 않는다 — 늦게 뜨는 것보다 안 뜨는 것이 나쁘다
const POSITION_WAIT_CAP_MS=8000;

// Match only this preset's unambiguous forward original turns. This has no role in judging
// speech or changing the transcript. Uncertain speech stays silent.
export function findReplayCue(text:string,cues:ReplayCue[],current:number){
 const value=normalize(text);if(value.length<4)return -1;
 const matches=cues.map((cue,index)=>({index,match:[cue.text,cue.spokenText].some(source=>{const key=normalize(source);return key.includes(value)||value.includes(key);})})).filter(entry=>entry.match&&entry.index>=Math.max(0,current));
 return matches.length===1?matches[0].index:-1;
}

const sleep=(ms:number)=>new Promise<void>(resolve=>{setTimeout(resolve,ms);});

/**
 * 시연 음원·기록 재생의 소리를 맡는다.
 *
 * **음원을 마이크가 듣고 있는 방으로 취급한다.** 예전에는 전사가 도착할 때마다 그
 * 대사 구간만 잘라 틀었다. 그래서 (1) 소리가 대사마다 끊기고 (2) 같은 구간에서 나온
 * 둘째·셋째 문장은 기다리지 않고 바로 화면에 얹혀 글자가 소리를 앞질렀다.
 *
 * 지금은 `ready` 순간부터 음원을 처음부터 끝까지 **연속 재생**하고, 재생 위치를 시계로
 * 삼아 전사를 공개한다. 서버(`replay`·`trace` 둘 다)가 실시간 간격을 지켜 보내므로 두
 * 시계가 같은 0초에서 출발한다.
 *
 *     공개 조건   그 발화가 속한 대사 구간의 끝을 재생 위치가 지났고,
 *                 앞 발화를 올린 뒤 `REVEAL_GAP_MS` 가 지났을 때
 *
 * 시각을 지어내지 않는다. 기다리는 기준은 매니페스트에 적힌 실측 구간 경계뿐이고,
 * 발화에 붙는 `t_ms` 는 서버가 준 값을 그대로 쓴다. 여기서 정하는 것은 화면에 올리는
 * 순간의 간격뿐이다.
 */
export class ReplayAudio {
 private context:AudioContext|null=null;private gain:GainNode|null=null;private buffer:AudioBuffer|null=null;private manifest:Manifest|null=null;
 private source:AudioBufferSourceNode|null=null;
 // 연속 재생의 기준점. `startedAt` 은 재생을 건 시점의 context 시계, `offset` 은 그때
 // 음원의 몇 초부터 틀었는지다. 재생 위치 = (지금 - startedAt) + offset
 private startedAt=0;private offset=0;private running=false;
 private pendingStart=false;private lastReveal=0;
 private cursor=-1;private played=new Set<string>();private cancelled=false;private enabled=true;private visible=true;private preset?:{id:string;version:string};
 private state:ReplayAudioState={enabled:true,status:'loading'};
 constructor(private notify:(state:ReplayAudioState)=>void){}
 private report(value:Partial<ReplayAudioState>){if(this.cancelled)return;this.state={...this.state,...value,enabled:this.enabled};this.notify(this.state);}
 async prepare(presetId:string,packVersion:string){
  try{
   this.preset={id:presetId,version:packVersion};this.report({status:'loading',error:undefined});
   // No hardcoded preset list: prepare-replay-audio.cjs bundles whatever ships with audio,
   // and a stale list here reported "not prepared" for presets that were in fact bundled.
   // Called directly from the start/resume click, before the first await.
   if(!this.context){this.context=new AudioContext();this.gain=this.context.createGain();this.gain.connect(this.context.destination);}
   void this.context.resume().then(()=>{if(this.context?.state==='suspended')this.report({status:'blocked',error:'소리 켜기를 눌러 음성 재생을 허용해 주세요.'});}).catch(()=>this.report({status:'blocked',error:'소리 켜기를 눌러 음성 재생을 허용해 주세요.'}));
   const response=await fetch(`/replay/${presetId}/manifest.json`,{signal:AbortSignal.timeout(15000)});
   if(response.status===404)throw new Error('이 프리셋의 재생 음원이 준비되지 않았습니다.');
   if(!response.ok)throw new Error('재생 음원 정보를 불러오지 못했습니다.');
   const manifest=await response.json() as Manifest;
   if(manifest.presetId!==presetId||manifest.packVersion!==packVersion||manifest.audioUrl!==`/replay/${presetId}/audio.wav`)throw new Error('상담과 재생 음원의 버전이 다릅니다.');
   const audio=await fetch(manifest.audioUrl,{signal:AbortSignal.timeout(15000)});if(!audio.ok)throw new Error('재생 음원을 불러오지 못했습니다.');
   const bytes=await audio.arrayBuffer();if(this.cancelled||!this.context)return;
   this.buffer=await this.context.decodeAudioData(bytes);if(this.cancelled)return;this.manifest=manifest;
   this.report({status:this.context.state==='running'?'ready':'blocked',error:this.context.state==='running'?undefined:'소리 켜기를 눌러 음성 재생을 허용해 주세요.'});
   // 음원을 늦게 받아 `ready` 를 이미 놓쳤으면 여기서 건다
   if(this.pendingStart)this.begin();
  }catch(reason){this.report({status:'unavailable',error:reason instanceof Error?reason.message:'음성 재생을 준비하지 못했습니다.'});}
 }
 /** 상담이 `ready` 를 받은 순간. 서버가 음원을 STT 로 흘리기 시작하는 시점과 같다. */
 beginPlayback(){this.pendingStart=true;if(this.buffer&&!this.running)this.begin();}
 private begin(){
  const context=this.context,buffer=this.buffer;if(!context||!buffer||this.cancelled||this.running)return;
  try{
   const source=context.createBufferSource();source.buffer=buffer;source.connect(this.gain!);
   // 이어보기면 이미 지나간 대사 뒤부터 잇는다. 처음부터면 0 이다
   const from=Math.min(this.offset,Math.max(0,buffer.duration-0.05));
   source.onended=()=>{source.disconnect();if(this.source===source){this.source=null;this.running=false;this.report({status:'ready'});}};
   source.start(0,from);this.source=source;this.startedAt=context.currentTime;this.offset=from;this.running=true;
   this.report({status:'playing',error:undefined});
  }catch{this.report({status:'unavailable',error:'음성을 재생하지 못했습니다. 소리 다시 시도를 눌러 주세요.'});}
 }
 /** 음원의 몇 초를 지나고 있는지. 재생 중이 아니면 마지막으로 멈춘 자리. */
 position(){return this.running&&this.context?(this.context.currentTime-this.startedAt)+this.offset:this.offset;}
 async toggle(){
  if(this.state.status==='unavailable'&&this.preset){await this.prepare(this.preset.id,this.preset.version);return;}
  if(!this.context||!this.buffer)return;
  if(this.context.state!=='running'){
   try{await this.context.resume();}catch{this.report({status:'blocked',error:'브라우저의 소리 재생 권한을 확인해 주세요.'});return;}
   if(String(this.context.state)!=='running')return;
   this.enabled=true;
  }else this.enabled=!this.enabled;
  if(this.gain)this.gain.gain.value=this.enabled?1:0;
  // 소리를 끄더라도 재생은 계속 돈다. 위치가 곧 시계이고, 그 시계로 전사를 공개한다
  if(this.pendingStart&&!this.running)this.begin();
  this.report({status:this.running?'playing':'ready',error:undefined});
 }
 /**
  * 발화 하나를 화면에 올린다. 소리보다 앞서지 않게, 그리고 앞 발화와 붙지 않게 기다린다.
  *
  * 기다림을 여기서 하는 것이 요점이다. 호출하는 쪽이 서버 메시지를 한 줄로 세워
  * 처리하므로, 이 함수가 늦으면 그 발화에 딸린 판정·경보도 함께 늦어 순서가 안 뒤집힌다.
  */
 async present(message:ServerMessage,show:()=>void){
  if(this.cancelled)return;
  if(message.t!=='utterance'||!this.visible){show();return;}
  const cue=this.matchCue(String(message.text??''));
  if(this.running)await this.waitForPosition(cue?cue.end:0);
  await this.waitForGap();
  if(this.cancelled)return;
  this.lastReveal=Date.now();
  if(cue)this.report({cueId:cue.id});
  show();
 }
 /** 이 발화가 원본의 어느 대사인지. 못 찾으면 같은 구간의 둘째·셋째 문장이라는 뜻이다. */
 private matchCue(text:string){
  if(!this.manifest)return null;
  const index=findReplayCue(text,this.manifest.cues,this.cursor);
  if(index<0)return null;
  const cue=this.manifest.cues[index];
  if(this.played.has(cue.id))return null;
  this.cursor=index;this.played.add(cue.id);
  return cue;
 }
 private async waitForPosition(seconds:number){
  const deadline=Date.now()+POSITION_WAIT_CAP_MS;
  while(!this.cancelled&&this.running&&this.position()<seconds&&Date.now()<deadline)await sleep(120);
 }
 private async waitForGap(){
  const left=REVEAL_GAP_MS-(Date.now()-this.lastReveal);
  if(left>0)await sleep(left);
 }
 restoreTranscript(texts:string[]){
  if(!this.manifest)return;
  for(const text of texts){const index=findReplayCue(text,this.manifest.cues,this.cursor);if(index>=0){this.cursor=index;this.played.add(this.manifest.cues[index].id);}}
  // 이어보기는 이미 들은 대사를 다시 틀지 않는다. 마지막으로 지나간 자리에서 잇는다
  if(this.cursor>=0)this.offset=this.manifest.cues[this.cursor].end;
 }
 setVisible(value:boolean){this.visible=value;if(!value)this.stop();}
 stop(){
  const source=this.source;this.source=null;
  // 멈춘 자리를 기억해 둔다. 다시 걸면 거기서 잇는다
  if(this.running)this.offset=this.position();
  this.running=false;this.pendingStart=false;
  if(source){source.onended=null;try{source.stop();}catch{}source.disconnect();}
  this.report({status:this.state.status==='playing'?'ready':this.state.status,cueId:undefined});
 }
 dispose(){this.stop();this.cancelled=true;void this.context?.close().catch(()=>{});this.context=null;this.buffer=null;}
}
