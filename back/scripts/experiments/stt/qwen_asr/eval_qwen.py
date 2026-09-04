# Wrap ../nv_asr/merge_eval.py (unchanged) over the sub-results of offline_*.json / stream_*.json
import json, sys, subprocess, wave, os
src=sys.argv[1]; d=json.load(open(src)); tag=os.path.basename(src).replace(".json","")
modes={}
if "full" in d["preset-dep-a"]:
    modes["full"]={p:{"text":d[p]["full"]["text"],"steps":[]} for p in ("preset-dep-a","preset-loan-b")}
    modes["seg"]={p:{"text":" ".join(x["text"] for x in sorted(d[p]["seg"]["segments"],key=lambda x:x["s"])),"words":d[p]["seg"]["words"]} for p in ("preset-dep-a","preset-loan-b")}  # diar segments are grouped by speaker -> sort by time
    cl={}
    for p in ("preset-dep-a","preset-loan-b"):
        base=f"/home/me/projects/share/scenarios/{p}"; gt=json.load(open(f"{base}/script.json"))["lines"]; words=[]
        for l,c in zip(gt,d[p]["clips"]["lines"]):
            st=l["start_ms"]/1000; wv=wave.open(f"{base}/clips/{l['id']}.wav"); en=st+wv.getnframes()/wv.getframerate(); ws=c["hyp"].split()
            for k,w in enumerate(ws): words.append({"w":w,"s":st+(en-st)*k/len(ws),"e":st+(en-st)*(k+1)/len(ws)})
        cl[p]={"text":" ".join(c["hyp"] for c in d[p]["clips"]["lines"]),"words":words}
    modes["clips"]=cl
else:
    modes["stream"]={p:{"text":" ".join(w["w"] for w in sorted(d[p]["words"],key=lambda w:w["s"])),"words":d[p]["words"]} for p in ("preset-dep-a","preset-loan-b")}
for k,v in modes.items():
    f=f"tmp_{tag}_{k}.json"; json.dump(v,open(f,"w"),ensure_ascii=False)
    txt=subprocess.run([sys.executable,"../nv_asr/merge_eval.py",f],capture_output=True,text=True).stdout
    open(f"eval_{tag}_{k}.txt","w").write(txt); os.rename(f.replace(".json","_eval.json"),f"eval_{tag}_{k}.json"); os.remove(f)
    print(f"### {k}"); print("\n".join(l for l in txt.splitlines() if l.startswith("==") or l.startswith("   keywords")))
