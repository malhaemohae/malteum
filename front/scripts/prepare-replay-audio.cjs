// Bundle the two public, fictional demo recordings inside the frontend Docker
// build context. Never copy user uploads, credentials or expected judgements.
const fs=require('node:fs');const path=require('node:path');const crypto=require('node:crypto');const assert=require('node:assert/strict');
const front=path.resolve(__dirname,'..');const check=process.argv.includes('--check');
for(const preset of ['preset-dep-a','preset-loan-b']){
 const source=path.resolve(front,'../assets/scenarios',preset);const target=path.join(front,'public/replay',preset);
 const script=JSON.parse(fs.readFileSync(path.join(source,'script.json'),'utf8'));const audio=fs.readFileSync(path.join(source,'audio.wav'));
 assert.equal(audio.toString('ascii',0,4),'RIFF');assert.equal(audio.toString('ascii',8,12),'WAVE');
 let offset=12;let pcm;let rate;let sampleRate;
 while(offset+8<=audio.length){const kind=audio.toString('ascii',offset,offset+4);const length=audio.readUInt32LE(offset+4);const start=offset+8;
  if(kind==='fmt '){assert.equal(audio.readUInt16LE(start),1);assert.equal(audio.readUInt16LE(start+2),1);sampleRate=audio.readUInt32LE(start+4);rate=audio.readUInt32LE(start+8);assert.equal(audio.readUInt16LE(start+14),16);}
  if(kind==='data')pcm=audio.subarray(start,start+length);offset=start+length+(length%2);
 }
 assert.ok(pcm&&rate&&sampleRate);const duration=pcm.length/rate;
 // Trim only quiet tails in the known per-turn interval; never synthesize speech.
 const cues=script.lines.map((line,index)=>{
  const start=line.start_ms/1000;let end=script.lines[index+1]?.start_ms/1000||duration;
  const lower=Math.floor(start*sampleRate);let upper=Math.min(pcm.length/2,Math.floor(end*sampleRate));
  while(upper>lower&&Math.abs(pcm.readInt16LE((upper-1)*2))<180)upper--;
  end=Math.min(end,upper/sampleRate+.06);
  assert.ok(end>start,`silent cue ${line.id}`);
  return {id:line.id,start,end,text:line.text,spokenText:line.tts_text||line.text};
 });
 const manifest=JSON.stringify({presetId:preset,packVersion:script.pack_version,audioUrl:`/replay/${preset}/audio.wav`,sha256:crypto.createHash('sha256').update(audio).digest('hex'),duration,cues},null,2)+'\n';
 if(check){assert.equal(fs.readFileSync(path.join(target,'manifest.json'),'utf8'),manifest);assert.deepEqual(fs.readFileSync(path.join(target,'audio.wav')),audio);}
 else{fs.mkdirSync(target,{recursive:true});fs.writeFileSync(path.join(target,'manifest.json'),manifest);fs.copyFileSync(path.join(source,'audio.wav'),path.join(target,'audio.wav'));}
 console.log(`${check?'Verified':'Prepared'} ${preset}: ${cues.length} original audio turns`);
}
