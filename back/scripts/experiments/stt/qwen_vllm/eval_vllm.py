# Host-side evaluation of out/<tag>.json produced by run_stream_vllm.py (run from qwen_vllm/ with ../qwen_asr/.venv_gpu python).
# Calls ../nv_asr/merge_eval.py unchanged for CER / keywords / speaker; adds latency (real-time queue replay),
# per-step time, revision (retraction) counts and Arabic-digit check.
import json, sys, os, subprocess, re, numpy as np
src = sys.argv[1]; d = json.load(open(src)); tag = os.path.basename(src)[:-5]
P = ("preset-dep-a", "preset-loan-b"); summ = {"tag": tag, "model": d["model"], "mode": d["mode"], "chunk_s": d["chunk_s"],
     "load_s": d["load_s"], "gpu_used_mb_after_load": d["gpu_used_mb_after_load"]}
PUNCT = re.compile(r"[\s\.,\?!·~…'\"()\[\]:;\-–—「」『』]")   # same normalisation as merge_eval: a revision = content change, not punctuation
def norm(t): return PUNCT.sub("", t)
def cp(a, b):
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]: n += 1
    return n
me_in = {}
for p in P:
    r = d[p]; steps = r["steps"]
    # --- real-time replay: chunk i arrives at audio_end_s, one GPU processes serially ---
    done = 0.0; first_partial = {}; final_lat = {}; utt_start = {u["s"]: u for u in r["utts"]}
    for s in steps:
        start = max(s["audio_end_s"], done); done = start + s["lat_s"]; s["done_s"] = done; s["rt_lat_s"] = done - s["audio_end_s"]
        if s["text"].strip() and s["utt"] not in first_partial: first_partial[s["utt"]] = done - s["seg_start"]
        if s["final"]: final_lat[s["utt"]] = done - s["audio_end_s"]
    # --- revisions within an utterance ---
    rev = 0; rev_chars = 0; n_pairs = 0; final_diff = 0; prev = None
    for s in steps:
        if prev is not None and prev["utt"] == s["utt"]:
            n_pairs += 1; a, b = norm(prev["text"]), norm(s["text"])
            if not b.startswith(a): rev += 1; rev_chars += len(a) - cp(a, b)
            if s["final"] and not b.startswith(a): final_diff += 1
        prev = s
    lats = np.array([s["lat_s"] for s in steps]); acc = np.array([s["accum_s"] for s in steps])
    fp = list(first_partial.values()); fl = list(final_lat.values())
    summ[p] = {"audio_s": r["audio_s"], "infer_s": r["infer_s"], "rtf": r["rtf"], "n_steps": len(steps), "n_utts": len(r["utts"]),
        "step_lat_mean": float(lats.mean()), "step_lat_p50": float(np.median(lats)), "step_lat_max": float(lats.max()),
        "step_lat_short(<=6s accum)": float(lats[acc <= 6].mean()) if (acc <= 6).any() else None,
        "step_lat_long(>20s accum)": float(lats[acc > 20].mean()) if (acc > 20).any() else None,
        "first_partial_mean": float(np.mean(fp)) if fp else None, "first_partial_max": float(np.max(fp)) if fp else None,
        "final_lat_mean": float(np.mean(fl)), "final_lat_max": float(np.max(fl)),
        "rt_lag_max": float(max(s["rt_lat_s"] for s in steps)), "revisions": rev, "revision_pairs": n_pairs, "revision_chars": rev_chars,
        "final_differs_from_last_partial": final_diff, "arabic_digits": bool(re.search(r"\d", r["text"])), "gpu_used_mb_peak": r.get("gpu_used_mb_peak")}
    # --- merge_eval input: word placement ---
    if d["mode"] == "seg":
        words = []
        for u in r["utts"]:
            ws = u["text"].split()
            for k, w in enumerate(ws): words.append({"w": w, "s": u["s"] + (u["e"]-u["s"])*k/len(ws), "e": u["s"] + (u["e"]-u["s"])*(k+1)/len(ws)})
        me_in[p] = {"text": r["text"], "words": words}
    else:  # continuous: assign the newly appended text of each step to that step's audio span
        ms = []; prev_t = ""
        for s in steps:
            t = s["text"].strip(); new = t[cp(prev_t, t):]; prev_t = t
            ms.append({"new": new, "audio_end_s": s["audio_end_s"]})
        me_in[p] = {"text": r["text"], "steps": ms}
f = f"tmp_{tag}.json"; json.dump(me_in, open(f, "w"), ensure_ascii=False)
txt = subprocess.run([sys.executable, "../nv_asr/merge_eval.py", f], capture_output=True, text=True); os.remove(f)
open(f"out/eval_{tag}.txt", "w").write(txt.stdout + txt.stderr); os.replace(f.replace(".json", "_eval.json"), f"out/eval_{tag}_merge.json")
me = json.load(open(f"out/eval_{tag}_merge.json"))
for p in P:
    summ[p].update({"full_cer": me[p]["full_cer"], "full_cer_spoken": me[p]["full_cer_spoken"], "line_cer_sum": me[p]["line_cer_sum"],
                    "speaker": f'{me[p]["speaker_correct"]}/{me[p]["n_lines"]}', "kw_hit": sum(1 for v in me[p]["keywords"].values() if v),
                    "kw_n": len(me[p]["keywords"]), "kw_missing": [k for k, v in me[p]["keywords"].items() if not v]})
json.dump(summ, open(f"out/eval_{tag}_summary.json", "w"), ensure_ascii=False, indent=1)
print("\n".join(l for l in txt.stdout.splitlines() if l.startswith("==") or l.startswith("   keywords")))
for p in P:
    s = summ[p]
    print(f"{tag} {p}: rtf={s['rtf']:.3f} steps={s['n_steps']} step_lat mean/p50/max={s['step_lat_mean']:.3f}/{s['step_lat_p50']:.3f}/{s['step_lat_max']:.3f}"
          f" short/long={s['step_lat_short(<=6s accum)']}/{s['step_lat_long(>20s accum)']} first_partial mean/max={s['first_partial_mean']}/{s['first_partial_max']}"
          f" final_lat mean/max={s['final_lat_mean']:.3f}/{s['final_lat_max']:.3f} rt_lag_max={s['rt_lag_max']:.2f} rev={s['revisions']}/{s['revision_pairs']} ({s['revision_chars']} ch)"
          f" final_diff={s['final_differs_from_last_partial']} digits={s['arabic_digits']} kw={s['kw_hit']}/{s['kw_n']} missing={s['kw_missing']}")
