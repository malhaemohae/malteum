# Merge Nemotron ASR output (offline words or streaming steps) with Streaming Sortformer segments, evaluate per GT line.
import json, wave, sys, re, itertools
out=json.load(open(sys.argv[1]))
diar=json.load(open("../diar/streaming_out.json"))
LANGTAG=re.compile(r"\s*<[a-z]{2}-[A-Z]{2}>")
PUNCT=re.compile(r"[\s\.,\?!·~…'\"()\[\]:;\-–—「」『』]")
def norm(s): return PUNCT.sub("",s)
def lev(a,b):
    prev=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        cur=[i]
        for j,cb in enumerate(b,1):
            cur.append(min(prev[j]+1,cur[j-1]+1,prev[j-1]+(ca!=cb)))
        prev=cur
    return prev[-1]
KW={"우대이자율":[],"기본이자율":[],"과세":[],"14%":["14퍼센트","십사퍼센트","14프로","십사프로"],"15.4%":["15.4퍼센트","십오점사퍼센트","15.4프로"],
    "중도해지이율":[],"차감률":[],"예금자보호":[],"1억":["일억"],"딸이알려준계좌":[],"DSR":["디에스알","디에스아르","총부채원리금상환비율"],
    "무조건승인됩니다":[],"다른상환방식은안":[],"연체가산이자율":[],"3%":["3퍼센트","삼퍼센트","3프로","삼프로"]}
report={}
for p in ["preset-dep-a","preset-loan-b"]:
    base=f"/home/me/projects/share/scenarios/{p}"; gt=json.load(open(f"{base}/script.json"))["lines"]
    segs=[(float(a),float(b),s) for a,b,s in (x.split() for x in diar[p]["segments"])]
    # units: (word, t_mid)
    units=[]
    if "words" in out[p]:
        units=[(w["w"],(w["s"]+w["e"])/2) for w in out[p]["words"] if not LANGTAG.fullmatch(w["w"])]
    else:
        prev_end=0.0
        for st in out[p]["steps"]:
            ws=st["new"].split(); a,b=prev_end,st["audio_end_s"]
            for k,w in enumerate(ws): units.append((w,a+(b-a)*(k+0.5)/len(ws)))
            prev_end=b
    lines=[]
    for l in gt:
        wv=wave.open(f"{base}/clips/{l['id']}.wav"); dur=wv.getnframes()/wv.getframerate()
        lines.append({"id":l["id"],"spk":l["speaker"],"st":l["start_ms"]/1000,"en":l["start_ms"]/1000+dur,"gt":l["text"],"gts":l.get("tts_text",l["text"]),"hyp":[],"spks":[]})
    def spk_at(t):
        best,bd=None,9e9
        for a,b,s in segs:
            d=0 if a<=t<=b else min(abs(t-a),abs(t-b))
            if d<bd: bd,best=d,s
        return best if bd<=0.5 else None
    for w,t in units:
        best,bd=None,9e9
        for L in lines:
            d=0 if L["st"]<=t<=L["en"] else min(abs(t-L["st"]),abs(t-L["en"]))
            if d<bd: bd,best=d,L
        if bd<=1.5:
            best["hyp"].append(w); s=spk_at(t)
            if s: best["spks"].append(s)
    spk_ids=sorted({s for _,_,s in segs}); tot_e=tot_n=0
    for L in lines:
        L["hyp"]=" ".join(L["hyp"]); g,h=norm(L["gt"]),norm(L["hyp"])
        L["err"]=lev(g,h); L["n"]=len(g); L["cer"]=L["err"]/max(1,len(g)); tot_e+=L["err"]; tot_n+=len(g)
        L["pred"]=max(set(L["spks"]),key=L["spks"].count) if L["spks"] else None
    best_map,best_n=None,-1
    for t,c in itertools.permutations(spk_ids,2):
        n=sum(1 for L in lines if (L["spk"]=="teller" and L["pred"]==t) or (L["spk"]=="customer" and L["pred"]==c))
        if n>best_n: best_n,best_map=n,(t,c)
    full_gt=norm("".join(L["gt"] for L in lines)); full_hyp=norm(LANGTAG.sub("",out[p]["text"]))
    full_cer=lev(full_gt,full_hyp)/len(full_gt)
    full_gts=norm("".join(L["gts"] for L in lines)); full_cer_spoken=lev(full_gts,full_hyp)/len(full_gts)
    kw={}
    for k,alts in KW.items():
        if norm(k) not in full_gt: continue
        hit=[v for v in [k]+alts if norm(v) in full_hyp]
        kw[k]=hit[0] if hit else None
    r={"line_cer_sum":tot_e/tot_n,"full_cer":full_cer,"full_cer_spoken":full_cer_spoken,"speaker_correct":best_n,"n_lines":len(lines),"map":best_map,
       "keywords":kw,"lines":[{k:L[k] for k in ("id","spk","pred","cer","gt","hyp")} for L in lines]}
    report[p]=r
    print(f"== {p}: line-CER {tot_e/tot_n:.3%} (sum-of-lines)  full-transcript CER {full_cer:.3%} (vs spoken-form ref {full_cer_spoken:.3%})  speaker {best_n}/{len(lines)} map teller={best_map[0]} customer={best_map[1]}")
    print("   keywords:", {k:(v if v else 'MISSING') for k,v in kw.items()})
    for L in lines:
        flag="" if ((L["spk"]=="teller" and L["pred"]==best_map[0]) or (L["spk"]=="customer" and L["pred"]==best_map[1])) else " SPK-WRONG"
        print(f"   {L['id']} {L['spk']:8s} cer={L['cer']:.2f}{flag}\n      GT : {L['gt']}\n      HYP: {L['hyp']}")
json.dump(report,open(sys.argv[1].replace(".json","_eval.json"),"w"),ensure_ascii=False,indent=1)
