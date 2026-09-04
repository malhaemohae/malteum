# Nemotron 3.5 ASR cache-aware streaming simulation on CPU. argv: right_context (0,1,3,6,13)
import time, json, torch, resource, sys
rc=int(sys.argv[1]) if len(sys.argv)>1 else 13
torch.set_num_threads(8)
from nemo.collections.asr.models import ASRModel
from nemo.collections.asr.parts.utils.streaming_utils import CacheAwareStreamingAudioBuffer
from omegaconf import open_dict
t=time.time()
m=ASRModel.from_pretrained("nvidia/nemotron-3.5-asr-streaming-0.6b", map_location="cpu").eval()
m.encoder.set_default_att_context_size([56,rc])
dec=m.cfg.decoding
with open_dict(dec):
    dec.strategy="greedy_batch"; dec.greedy.max_symbols=10; dec.fused_batch_size=-1
m.change_decoding_strategy(dec)
m.set_inference_prompt("ko-KR")
if hasattr(m.decoding,"set_strip_lang_tags"): m.decoding.set_strip_lang_tags(True)
print("load_s",round(time.time()-t,1),"streaming_cfg",m.encoder.streaming_cfg,flush=True)
chunk_s=(rc+1)*0.08
out={"right_context":rc,"chunk_s":chunk_s}
for p in ["preset-dep-a","preset-loan-b"]:
    wav=f"/home/me/projects/share/scenarios/{p}/audio.wav"
    buf=CacheAwareStreamingAudioBuffer(model=m, online_normalization=False, pad_and_drop_preencoded=False)
    buf.append_audio_file(wav, stream_id=-1)
    cache_ch,cache_t,cache_len=m.encoder.get_initial_cache_state(batch_size=1)
    prev=None; pred=None; steps=[]; prev_text=""; t0=time.time(); step_times=[]
    for i,(ca,cl) in enumerate(iter(buf)):
        ts=time.time()
        with torch.inference_mode():
            pred,texts,cache_ch,cache_t,cache_len,prev=m.conformer_stream_step(
                processed_signal=ca,processed_signal_length=cl,cache_last_channel=cache_ch,
                cache_last_time=cache_t,cache_last_channel_len=cache_len,
                keep_all_outputs=buf.is_buffer_empty(),previous_hypotheses=prev,previous_pred_out=pred,
                drop_extra_pre_encoded=(0 if i==0 else m.encoder.streaming_cfg.drop_extra_pre_encoded),
                return_transcription=True)
        step_times.append(time.time()-ts)
        text=texts[0].text if hasattr(texts[0],"text") else texts[0]
        if text!=prev_text:
            # audio time at end of this chunk (first chunk includes pre-encode cache/extra)
            steps.append({"step":i,"audio_end_s":min((i+1)*chunk_s,buf.streams_length[0].item()*0.01),"new":text[len(prev_text):] if text.startswith(prev_text) else text,"full_len":len(text)})
            prev_text=text
    dt=time.time()-t0
    print(p,"steps",i+1,"infer_s",round(dt,1),"mean_step_ms",round(1000*sum(step_times)/len(step_times)),"max_step_ms",round(1000*max(step_times)),flush=True)
    print("  TEXT:",prev_text[:300],flush=True)
    out[p]={"infer_s":dt,"n_steps":i+1,"mean_step_ms":1000*sum(step_times)/len(step_times),"max_step_ms":1000*max(step_times),"text":prev_text,"steps":steps}
out["peak_rss_mb"]=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
json.dump(out,open(f"stream_out_rc{rc}.json","w"),ensure_ascii=False,indent=1)
print("peak_rss_mb",round(out["peak_rss_mb"]))
