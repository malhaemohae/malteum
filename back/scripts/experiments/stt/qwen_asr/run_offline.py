# Qwen3-ASR offline (transformers backend, CPU): (1) full file, (2) per Sortformer segment, (3) per GT clip
import sys, time, json, resource, wave
import numpy as np, soundfile as sf, torch, os
DEV=os.environ.get("DEV","cpu"); DT=torch.bfloat16 if DEV.startswith("cuda") else torch.float32
MODEL=sys.argv[1]; TAG=sys.argv[2]; torch.set_num_threads(8)
t=time.time()
from qwen_asr import Qwen3ASRModel
m=Qwen3ASRModel.from_pretrained(MODEL, dtype=DT, device_map=DEV, max_inference_batch_size=8, max_new_tokens=2048)
load_s=time.time()-t; print("load_s",round(load_s,1),flush=True)
diar=json.load(open("../diar/streaming_out.json"))
out={"model":MODEL,"load_s":load_s,"threads":torch.get_num_threads(),"dtype":str(DT),"device":DEV}
for p in ["preset-dep-a","preset-loan-b"]:
    base=f"/home/me/projects/share/scenarios/{p}"
    wav,sr=sf.read(f"{base}/audio.wav",dtype="float32"); assert sr==16000
    # (1) full file
    t=time.time(); r=m.transcribe(audio=(wav,sr), language="Korean")[0]; dt=time.time()-t
    print(p,"full infer_s",round(dt,1),"lang",r.language,"|",r.text[:300],flush=True)
    full={"infer_s":dt,"text":r.text,"language":r.language}
    # (2) per Sortformer segment (batched); words placed uniformly inside segment -> word-like units for merge_eval
    segs=[(float(a),float(b),s) for a,b,s in (x.split() for x in diar[p]["segments"])]
    t=time.time(); rs=m.transcribe(audio=[(wav[int(a*sr):int(b*sr)],sr) for a,b,_ in segs], language=["Korean"]*len(segs)); dt=time.time()-t
    words=[]; segtxt=[]
    for (a,b,s),r in zip(segs,rs):
        ws=r.text.split(); segtxt.append({"s":a,"e":b,"spk":s,"text":r.text})
        for k,w in enumerate(ws):
            ws_=a+(b-a)*k/len(ws); we_=a+(b-a)*(k+1)/len(ws); words.append({"w":w,"s":ws_,"e":we_})
    print(p,"seg infer_s",round(dt,1),"nseg",len(segs),flush=True)
    seg={"infer_s":dt,"text":" ".join(x["text"] for x in segtxt),"words":words,"segments":segtxt}
    # (3) per GT clip (oracle segmentation)
    gt=json.load(open(f"{base}/script.json"))["lines"]
    t=time.time(); rc=m.transcribe(audio=[f"{base}/clips/{l['id']}.wav" for l in gt], language=["Korean"]*len(gt)); dt=time.time()-t
    clips=[{"id":l["id"],"gt":l["text"],"gts":l.get("tts_text",l["text"]),"hyp":r.text} for l,r in zip(gt,rc)]
    print(p,"clip infer_s",round(dt,1),flush=True)
    out[p]={"full":full,"seg":seg,"clips":{"infer_s":dt,"lines":clips}}
if DEV.startswith("cuda"): out["peak_gpu_mb"]=torch.cuda.max_memory_allocated()/2**20; print("peak_gpu_mb",round(out["peak_gpu_mb"]))
out["peak_rss_mb"]=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
json.dump(out,open(f"offline_{TAG}.json","w"),ensure_ascii=False,indent=1)
print("peak_rss_mb",round(out["peak_rss_mb"]))
