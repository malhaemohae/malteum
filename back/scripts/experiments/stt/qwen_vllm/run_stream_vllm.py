# Qwen3-ASR official streaming API (vLLM backend) driven like a live stream — runs INSIDE the container.
# Audio is pushed in time order in small pieces (--push-ms); the package itself buffers to chunk_size_sec.
#   --mode seg : one streaming state per Sortformer segment (utterance-level, like the earlier "seg" mode)
#   --mode full: one streaming state for the whole file (continuous, no cutting)
# Raw per-step records (audio position, wall time, partial text) go to out/<tag>.json; the host-side
# eval_vllm.py turns them into latency/revision/CER numbers.
import argparse, json, os, subprocess, time
import numpy as np, soundfile as sf

def gpu_used_mb():
    try: return int(subprocess.check_output(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"], text=True).split()[0])
    except Exception: return None

def stream_one(asr, wav, sr, t_off, a, push, args, steps, utt_idx):
    """Push wav (one utterance or the whole file) piecewise; record every step where a decode happened."""
    st = asr.init_streaming_state(language="Korean", chunk_size_sec=args.chunk,
                                  unfixed_chunk_num=args.unfixed_chunks, unfixed_token_num=args.unfixed_tokens)
    pos = 0; n_before = 0; t_utt0 = time.perf_counter()
    while pos < len(wav):
        piece = wav[pos:pos+push]; pos += len(piece)
        t0 = time.perf_counter(); asr.streaming_transcribe(piece, st); lat = time.perf_counter() - t0
        if st.chunk_id != n_before:            # a real decode step ran on this push
            n_before = st.chunk_id
            steps.append({"utt": utt_idx, "seg_start": a, "audio_end_s": a + pos/sr, "accum_s": len(st.audio_accum)/sr,
                          "lat_s": lat, "text": st.text, "final": False})
    t0 = time.perf_counter(); asr.finish_streaming_transcribe(st); lat = time.perf_counter() - t0
    steps.append({"utt": utt_idx, "seg_start": a, "audio_end_s": a + pos/sr, "accum_s": len(st.audio_accum)/sr,
                  "lat_s": lat, "text": st.text, "final": True})
    return st.text, time.perf_counter() - t_utt0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-ASR-1.7B"); ap.add_argument("--tag", required=True)
    ap.add_argument("--mode", choices=["seg","full"], default="seg"); ap.add_argument("--chunk", type=float, default=2.0)
    ap.add_argument("--push-ms", type=int, default=100, help="granularity of the simulated microphone push")
    ap.add_argument("--unfixed-chunks", type=int, default=2); ap.add_argument("--unfixed-tokens", type=int, default=5)
    ap.add_argument("--gpu-util", type=float, default=0.85); ap.add_argument("--max-model-len", type=int, default=4096); ap.add_argument("--max-new-tokens", type=int, default=32)
    ap.add_argument("--presets", default="preset-dep-a,preset-loan-b")
    ap.add_argument("--diar", default="/work/diar/streaming_out.json"); ap.add_argument("--data", default="/data/scenarios")
    ap.add_argument("--out", default="/work/qwen_vllm/out")
    args = ap.parse_args()
    from qwen_asr import Qwen3ASRModel
    gpu0 = gpu_used_mb(); t = time.perf_counter()
    asr = Qwen3ASRModel.LLM(model=args.model, gpu_memory_utilization=args.gpu_util, max_new_tokens=args.max_new_tokens,
                            max_model_len=args.max_model_len, max_num_seqs=1, enable_prefix_caching=True, limit_mm_per_prompt={"audio": 1})
    load_s = time.perf_counter() - t
    # warm-up so the first measured step does not include CUDA graph / cache init
    st = asr.init_streaming_state(language="Korean", chunk_size_sec=1.0); asr.streaming_transcribe(np.zeros(16000, np.float32), st); asr.finish_streaming_transcribe(st)
    gpu1 = gpu_used_mb()
    out = {"model": args.model, "mode": args.mode, "chunk_s": args.chunk, "push_ms": args.push_ms, "unfixed_chunk_num": args.unfixed_chunks,
           "unfixed_token_num": args.unfixed_tokens, "gpu_util": args.gpu_util, "max_new_tokens": args.max_new_tokens,
           "load_s": load_s, "gpu_used_mb_before": gpu0, "gpu_used_mb_after_load": gpu1}
    print(f"load_s={load_s:.1f} gpu_used_mb={gpu0}->{gpu1}", flush=True)
    diar = json.load(open(args.diar))
    for p in args.presets.split(","):
        wav, sr = sf.read(f"{args.data}/{p}/audio.wav", dtype="float32"); assert sr == 16000
        push = int(sr * args.push_ms / 1000); steps = []; utts = []; t0 = time.perf_counter()
        if args.mode == "seg":
            segs = sorted((float(a), float(b), s) for a, b, s in (x.split() for x in diar[p]["segments"]))
            for i, (a, b, s) in enumerate(segs):
                txt, wall = stream_one(asr, wav[int(a*sr):int(b*sr)], sr, 0.0, a, push, args, steps, i)
                utts.append({"s": a, "e": b, "spk": s, "text": txt, "wall_s": wall})
                print(f"{p} [{a:.1f}-{b:.1f}] steps={sum(1 for x in steps if x['utt']==i)} wall={wall:.2f}s | {txt}", flush=True)
        else:
            txt, wall = stream_one(asr, wav, sr, 0.0, 0.0, push, args, steps, 0)
            utts.append({"s": 0.0, "e": len(wav)/sr, "spk": None, "text": txt, "wall_s": wall})
            print(f"{p} [full] steps={len(steps)} wall={wall:.1f}s | {txt}", flush=True)
        infer = time.perf_counter() - t0; lats = [x["lat_s"] for x in steps]
        out[p] = {"audio_s": len(wav)/sr, "infer_s": infer, "rtf": infer/(len(wav)/sr), "text": " ".join(u["text"] for u in utts),
                  "utts": utts, "steps": steps, "gpu_used_mb_peak": gpu_used_mb()}
        print(f"{p} audio={len(wav)/sr:.0f}s infer={infer:.1f}s rtf={infer/(len(wav)/sr):.3f} steps={len(steps)} lat mean/max={np.mean(lats):.3f}/{max(lats):.3f}", flush=True)
    os.makedirs(args.out, exist_ok=True); f = f"{args.out}/{args.tag}.json"
    json.dump(out, open(f, "w"), ensure_ascii=False, indent=1); print("wrote", f)

if __name__ == "__main__":
    main()
