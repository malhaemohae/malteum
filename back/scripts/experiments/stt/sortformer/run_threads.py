import sys, time, torch, resource, logging
logging.disable(logging.CRITICAL)
torch.set_num_threads(int(sys.argv[1]))
from nemo.collections.asr.models import SortformerEncLabelModel
m = SortformerEncLabelModel.from_pretrained("nvidia/diar_sortformer_4spk-v1", map_location="cpu"); m.eval()
for p in ["preset-dep-a","preset-loan-b"]:
    t=time.time(); m.diarize(audio=[f"/home/me/projects/share/scenarios/{p}/audio.wav"], batch_size=1)
    print(f"threads={sys.argv[1]} {p} infer_s={time.time()-t:.1f}")
print("peak_rss_MB", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024)
