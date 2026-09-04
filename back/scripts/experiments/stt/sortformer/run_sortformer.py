import sys, time, json, torch
torch.set_num_threads(8)
t0=time.time()
from nemo.collections.asr.models import SortformerEncLabelModel
m = SortformerEncLabelModel.from_pretrained("nvidia/diar_sortformer_4spk-v1", map_location="cpu")
m.eval()
print("load_s", round(time.time()-t0,1), flush=True)
out={}
for p in ["preset-dep-a","preset-loan-b"]:
    wav=f"/home/me/projects/share/scenarios/{p}/audio.wav"
    t=time.time()
    segs = m.diarize(audio=[wav], batch_size=1, include_tensor_outputs=False)
    dt=time.time()-t
    print(p, "infer_s", round(dt,1), segs[0][:5], flush=True)
    out[p]={"infer_s":dt,"segments":segs[0]}
json.dump(out, open("sortformer_out.json","w"), ensure_ascii=False, indent=1)
