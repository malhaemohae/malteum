import json, sys, time, os, itertools, collections
import httpx
key = [l.split("=",1)[1].strip() for l in open("/home/me/projects/malteum/.env") if l.startswith("ELEVENLABS_API_KEY=")][0]
model = sys.argv[1] if len(sys.argv) > 1 else "scribe_v1"
out = {"model": model}
for p in ["preset-dep-a", "preset-loan-b"]:
    base = f"/home/me/projects/share/scenarios/{p}"
    t0 = time.perf_counter()
    with open(f"{base}/audio.wav", "rb") as f:
        r = httpx.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": key},
                       data={"model_id": model, "language_code": "ko", "diarize": "true",
                             "timestamps_granularity": "word", "tag_audio_events": "false"},
                       files={"file": ("audio.wav", f, "audio/wav")}, timeout=300)
    dt = time.perf_counter() - t0
    if r.status_code != 200:
        print(p, r.status_code, r.text[:300]); sys.exit(1)
    j = r.json()
    words = [{"w": w["text"], "s": w["start"], "e": w["end"], "spk": w.get("speaker_id")} for w in j["words"] if w.get("type") == "word"]
    out[p] = {"text": j["text"], "words": words, "api_s": round(dt, 1), "lang": j.get("language_code"), "lang_prob": j.get("language_probability")}
    # ElevenLabs 자체 화자 분리로 줄별 화자
    gt = json.load(open(f"{base}/script.json"))["lines"]
    import wave
    lines = []
    for l in gt:
        dur = (lambda w: w.getnframes()/w.getframerate())(wave.open(f"{base}/clips/{l['id']}.wav"))
        st, en = l["start_ms"]/1000, l["start_ms"]/1000 + dur
        spks = [w["spk"] for w in words if st - 0.3 <= (w["s"]+w["e"])/2 <= en + 0.3 and w["spk"]]
        pred = collections.Counter(spks).most_common(1)[0][0] if spks else None
        lines.append((l["speaker"], pred))
    ids = sorted({w["spk"] for w in words if w["spk"]})
    best = max(((sum(1 for g, pr in lines if (g == "teller" and pr == t) or (g == "customer" and pr == c)), (t, c)) for t, c in itertools.permutations(ids, 2)), default=(0, None))
    out[p]["own_diar"] = {"speaker_ids": ids, "line_acc": f"{best[0]}/{len(lines)}", "map": best[1]}
    print(p, f"api {dt:.1f}s  화자ID {ids}  자체 화자분리 줄 정확도 {best[0]}/{len(lines)}")
json.dump(out, open(f"{model}_out.json", "w"), ensure_ascii=False, indent=1)
