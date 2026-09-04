import json, wave, itertools, sys
outfile = sys.argv[1]
pred_all = json.load(open(outfile))
for p, res in pred_all.items():
    base=f"/home/me/projects/share/scenarios/{p}"
    d=json.load(open(f"{base}/script.json"))
    segs=[]
    for s in res["segments"]:
        a,b,spk=s.split(); segs.append((float(a),float(b),spk))
    spks=sorted({s[2] for s in segs})
    lines=[]
    for l in d["lines"]:
        w=wave.open(f"{base}/clips/{l['id']}.wav"); dur=w.getnframes()/w.getframerate()
        st=l["start_ms"]/1000; en=st+dur
        ov={k:0.0 for k in spks}
        for a,b,spk in segs:
            ov[spk]+=max(0.0,min(b,en)-max(a,st))
        best=max(ov,key=ov.get) if spks and max(ov.values())>0 else None
        lines.append((l["id"],l["speaker"],st,en,best,ov))
    # one-to-one mapping (teller,customer) maximizing correct
    best_map,best_n=None,-1
    for t,c in itertools.permutations(spks+[None]*(2-min(2,len(spks))) if len(spks)<2 else spks,2):
        n=sum(1 for _,gt,_,_,pr,_ in lines if pr is not None and ((gt=="teller" and pr==t) or (gt=="customer" and pr==c)))
        if n>best_n: best_n,best_map=n,(t,c)
    wrong=[(i,gt,pr,round(st,1),round(en,1),{k:round(v,1) for k,v in ov.items()}) for i,gt,st,en,pr,ov in lines
           if not ((gt=="teller" and pr==best_map[0]) or (gt=="customer" and pr==best_map[1]))]
    print(f"== {p}: pred speakers={len(spks)} {spks}, infer_s={res['infer_s']:.1f}")
    print(f"   mapping teller={best_map[0]} customer={best_map[1]}  correct {best_n}/{len(lines)}")
    for w_ in wrong: print("   WRONG", w_)
    # per-speaker total speech time
    tot={k:round(sum(b-a for a,b,s in segs if s==k),1) for k in spks}
    print("   speech_s per pred spk:", tot)
