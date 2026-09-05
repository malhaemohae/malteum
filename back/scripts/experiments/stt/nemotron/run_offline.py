# Nemotron 3.5 ASR: offline transcribe with word timestamps (ko-KR), CPU
import time, json, torch, resource, sys
torch.set_num_threads(int(sys.argv[1]) if len(sys.argv)>1 else 8)
t=time.time()
from nemo.collections.asr.models import ASRModel
m=ASRModel.from_pretrained("nvidia/nemotron-3.5-asr-streaming-0.6b", map_location="cpu").eval()
m.set_inference_prompt("ko-KR")
load_s=time.time()-t
print("load_s", round(load_s,1), flush=True)
out={"load_s":load_s,"threads":torch.get_num_threads()}
for p in ["preset-dep-a","preset-loan-b"]:
    wav=f"/home/me/projects/share/scenarios/{p}/audio.wav"
    t=time.time()
    import wave
    dur=wave.open(wav).getnframes()/16000
    mf=f"manifest_{p}.json"
    open(mf,"w").write(json.dumps({"audio_filepath":wav,"duration":dur,"text":"","lang":"ko-KR"},ensure_ascii=False)+"\n")
    hyp=m.transcribe([mf], batch_size=1, timestamps=True, target_lang="ko-KR")[0]
    dt=time.time()-t
    words=[{"w":w["word"],"s":w["start"],"e":w["end"]} for w in hyp.timestamp["word"]]
    print(p,"infer_s",round(dt,1),"| ",hyp.text[:200],flush=True)
    out[p]={"infer_s":dt,"text":hyp.text,"words":words}
out["peak_rss_mb"]=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
json.dump(out,open("offline_out.json","w"),ensure_ascii=False,indent=1)
print("peak_rss_mb",round(out["peak_rss_mb"]))
