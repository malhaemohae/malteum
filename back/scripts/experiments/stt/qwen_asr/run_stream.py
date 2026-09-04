# Qwen3-ASR streaming simulation on the transformers backend (CPU).
# Re-implements qwen_asr's vLLM-only streaming_transcribe(): every chunk_size_sec, re-feed the accumulated audio
# of the current utterance with the previously decoded text (minus the last unfixed_token_num tokens) as prefix.
# Utterance = Sortformer segment (state reset per segment), which keeps the O(n^2) re-encoding bounded on CPU.
import sys, time, json, resource
import numpy as np, soundfile as sf, torch, os
DEV=os.environ.get("DEV","cpu"); DT=torch.bfloat16 if DEV.startswith("cuda") else torch.float32
MODEL=sys.argv[1]; TAG=sys.argv[2]; CHUNK=float(sys.argv[3]) if len(sys.argv)>3 else 2.0
torch.set_num_threads(8)
from qwen_asr import Qwen3ASRModel
from qwen_asr.inference.utils import parse_asr_output
t=time.time()
m=Qwen3ASRModel.from_pretrained(MODEL, dtype=DT, device_map=DEV, max_new_tokens=48)
print("load_s",round(time.time()-t,1),flush=True)
diar=json.load(open("../diar/streaming_out.json"))
prompt_raw=m._build_text_prompt(context="", force_language="Korean")
tok=m.processor.tokenizer
def gen(prompt, audio):
    inputs=m.processor(text=[prompt], audio=[audio], return_tensors="pt", padding=True).to(m.model.device).to(m.model.dtype)
    ids=m.model.generate(**inputs, max_new_tokens=m.max_new_tokens)
    return m.processor.batch_decode(ids.sequences[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
out={"model":MODEL,"chunk_s":CHUNK,"unfixed_chunk_num":2,"unfixed_token_num":5}
for p in ["preset-dep-a","preset-loan-b"]:
    base=f"/home/me/projects/share/scenarios/{p}"
    wav,sr=sf.read(f"{base}/audio.wav",dtype="float32")
    segs=[(float(a),float(b),s) for a,b,s in (x.split() for x in diar[p]["segments"])]
    words=[]; steps=[]; texts=[]; t0=time.time()
    for a,b,s in segs:
        seg=wav[int(a*sr):int(b*sr)]; accum=np.zeros(0,np.float32); raw=""; cid=0; pos=0; n=int(CHUNK*sr)
        while pos<len(seg):
            chunk=seg[pos:pos+n]; pos+=len(chunk)
            if len(chunk)<n and cid>0 and len(chunk)<0.3*n: chunk_last=True  # tiny tail: still process (finish step)
            accum=np.concatenate([accum,chunk])
            prefix=""
            if cid>=2:
                ids=tok.encode(raw); k=5
                while True:
                    e=max(0,len(ids)-k); prefix=tok.decode(ids[:e]) if e>0 else ""
                    if "�" not in prefix or e==0: break
                    k+=1
            ts=time.time(); g=gen(prompt_raw+prefix, accum); lat=time.time()-ts
            raw=prefix+g; lang,txt=parse_asr_output(raw, user_language="Korean")
            steps.append({"seg_start":a,"audio_end_s":a+pos/sr,"accum_s":len(accum)/sr,"lat_s":lat,"text":txt}); cid+=1
        ws=txt.split(); texts.append(txt)
        for k,w in enumerate(ws): words.append({"w":w,"s":a+(b-a)*k/len(ws),"e":a+(b-a)*(k+1)/len(ws)})
        print(f"{p} [{a:.1f}-{b:.1f}] steps={cid} last_lat={lat:.2f}s | {txt}",flush=True)
    dt=time.time()-t0
    lats=[x["lat_s"] for x in steps]
    print(p,"total_s",round(dt,1),"steps",len(steps),"lat mean/max",round(np.mean(lats),2),round(max(lats),2),flush=True)
    out[p]={"infer_s":dt,"text":" ".join(texts),"words":words,"steps":steps}
if DEV.startswith("cuda"): out["peak_gpu_mb"]=torch.cuda.max_memory_allocated()/2**20; print("peak_gpu_mb",round(out["peak_gpu_mb"]))
out["peak_rss_mb"]=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
json.dump(out,open(f"stream_{TAG}.json","w"),ensure_ascii=False,indent=1)
print("peak_rss_mb",round(out["peak_rss_mb"]))
