import type { ServerMessage } from './api';

export type ReplayCue={id:string;start:number;end:number;text:string;spokenText:string};
export type ReplayAudioState={enabled:boolean;status:'loading'|'ready'|'playing'|'blocked'|'unavailable';error?:string;cueId?:string};
type Manifest={presetId:string;packVersion:string;audioUrl:string;duration:number;cues:ReplayCue[]};
const normalize=(text:string)=>text.toLowerCase().replace(/디에스알/g,'dsr').replace(/[^a-z0-9가-힣]/g,'');

// Match only this preset's unambiguous forward original turns. This has no role in judging
// speech or changing the transcript. Uncertain speech stays silent.
export function findReplayCue(text:string,cues:ReplayCue[],current:number){
 const value=normalize(text);if(value.length<4)return -1;
 const matches=cues.map((cue,index)=>({index,match:[cue.text,cue.spokenText].some(source=>{const key=normalize(source);return key.includes(value)||value.includes(key);})})).filter(entry=>entry.match&&entry.index>=Math.max(0,current));
 return matches.length===1?matches[0].index:-1;
}

export class ReplayAudio {
 private context:AudioContext|null=null;private gain:GainNode|null=null;private buffer:AudioBuffer|null=null;private manifest:Manifest|null=null;
 private source:AudioBufferSourceNode|null=null;private finished:Promise<void>=Promise.resolve();private finish:()=>void=()=>{};
 private cursor=-1;private played=new Set<string>();private cancelled=false;private generation=0;private enabled=true;private visible=true;private preset?:{id:string;version:string};
 private state:ReplayAudioState={enabled:true,status:'loading'};
 constructor(private notify:(state:ReplayAudioState)=>void){}
 private report(value:Partial<ReplayAudioState>){if(this.cancelled)return;this.state={...this.state,...value,enabled:this.enabled};this.notify(this.state);}
 async prepare(presetId:string,packVersion:string){
  try{
   this.preset={id:presetId,version:packVersion};this.report({status:'loading',error:undefined});
   if(!['preset-dep-a','preset-loan-b'].includes(presetId))throw new Error('이 프리셋의 재생 음원이 준비되지 않았습니다.');
   // Called directly from the start/resume click, before the first await.
   if(!this.context){this.context=new AudioContext();this.gain=this.context.createGain();this.gain.connect(this.context.destination);}
   void this.context.resume().then(()=>{if(this.context?.state==='suspended')this.report({status:'blocked',error:'소리 켜기를 눌러 음성 재생을 허용해 주세요.'});}).catch(()=>this.report({status:'blocked',error:'소리 켜기를 눌러 음성 재생을 허용해 주세요.'}));
   const response=await fetch(`/replay/${presetId}/manifest.json`,{signal:AbortSignal.timeout(15000)});if(!response.ok)throw new Error('재생 음원 정보를 불러오지 못했습니다.');
   const manifest=await response.json() as Manifest;
   if(manifest.presetId!==presetId||manifest.packVersion!==packVersion||manifest.audioUrl!==`/replay/${presetId}/audio.wav`)throw new Error('상담과 재생 음원의 버전이 다릅니다.');
   const audio=await fetch(manifest.audioUrl,{signal:AbortSignal.timeout(15000)});if(!audio.ok)throw new Error('재생 음원을 불러오지 못했습니다.');
   const bytes=await audio.arrayBuffer();if(this.cancelled||!this.context)return;
   this.buffer=await this.context.decodeAudioData(bytes);if(this.cancelled)return;this.manifest=manifest;
   this.report({status:this.context.state==='running'?'ready':'blocked',error:this.context.state==='running'?undefined:'소리 켜기를 눌러 음성 재생을 허용해 주세요.'});
  }catch(reason){this.report({status:'unavailable',error:reason instanceof Error?reason.message:'음성 재생을 준비하지 못했습니다.'});}
 }
 async toggle(){
  if(this.state.status==='unavailable'&&this.preset){await this.prepare(this.preset.id,this.preset.version);return;}
  if(!this.context||!this.buffer)return;
  if(this.context.state!=='running'){
   try{await this.context.resume();}catch{this.report({status:'blocked',error:'브라우저의 소리 재생 권한을 확인해 주세요.'});return;}
   if(String(this.context.state)!=='running')return;
   this.enabled=true;
  }else this.enabled=!this.enabled;
  if(this.gain)this.gain.gain.value=this.enabled?1:0;
  this.report({status:this.source?'playing':'ready',error:undefined});
 }
 async present(message:ServerMessage,show:()=>void){
  if(this.cancelled)return;
  if(message.t!=='utterance'||!this.visible||!this.manifest||!this.buffer||!this.context||this.context.state!=='running'){show();return;}
  const index=findReplayCue(String(message.text??''),this.manifest.cues,this.cursor);
  if(index<0||this.played.has(this.manifest.cues[index].id)){show();return;}
  const generation=this.generation;await this.finished;if(this.cancelled)return;if(generation!==this.generation){show();return;}
  const cue=this.manifest.cues[index];this.cursor=index;this.played.add(cue.id);
  // Always publish the received text, even if the audio device has disappeared.
  show();
  try{
   const source=this.context.createBufferSource();this.source=source;source.buffer=this.buffer;source.connect(this.gain!);
   this.finished=new Promise(resolve=>{this.finish=resolve;});
   source.onended=()=>{source.disconnect();if(this.source===source){this.source=null;this.finish();this.report({status:'ready',cueId:undefined});}};
   source.start(0,cue.start,Math.min(cue.end,this.buffer.duration)-cue.start);this.report({status:'playing',cueId:cue.id});
  }catch{this.stop();this.report({status:'unavailable',error:'음성을 재생하지 못했습니다. 소리 다시 시도를 눌러 주세요.'});}
 }
 restoreTranscript(texts:string[]){if(!this.manifest)return;for(const text of texts){const index=findReplayCue(text,this.manifest.cues,this.cursor);if(index>=0){this.cursor=index;this.played.add(this.manifest.cues[index].id);}}}
 setVisible(value:boolean){this.visible=value;if(!value)this.stop();}
 stop(){this.generation++;const source=this.source;this.source=null;if(source){source.onended=null;try{source.stop();}catch{}source.disconnect();}this.finish();this.finished=Promise.resolve();this.report({status:this.state.status==='playing'?'ready':this.state.status,cueId:undefined});}
 dispose(){this.stop();this.cancelled=true;void this.context?.close().catch(()=>{});this.context=null;this.buffer=null;}
}
