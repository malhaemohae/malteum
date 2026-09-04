import json, wave
out=json.load(open("sortformer_out.json"))
for p,res in out.items():
    base=f"/home/me/projects/share/scenarios/{p}"; d=json.load(open(f"{base}/script.json"))
    segs=[(float(a),float(b),s) for a,b,s in (x.split() for x in res["segments"])]
    m={"teller":"speaker_1","customer":"speaker_0"}
    tot_gt=wrong=missed=0; outside=0
    gt=[]
    for l in d["lines"]:
        w=wave.open(f"{base}/clips/{l['id']}.wav"); st=l["start_ms"]/1000; en=st+w.getnframes()/w.getframerate(); gt.append((st,en,l["speaker"]))
        tot_gt+=en-st
        for a,b,s in segs:
            o=max(0,min(b,en)-max(a,st))
            if s!=m[l["speaker"]]: wrong+=o
    pred_tot=sum(b-a for a,b,_ in segs)
    covered=sum(max(0,min(b,en)-max(a,st)) for a,b,_ in segs for st,en,_ in gt)
    print(f"{p}: gt_speech={tot_gt:.1f}s pred_speech={pred_tot:.1f}s overlap_with_gt={covered:.1f}s wrong_spk_inside_gt={wrong:.1f}s pred_outside_gt={pred_tot-covered:.1f}s n_segs={len(segs)}")
