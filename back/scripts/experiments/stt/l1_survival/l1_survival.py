"""실험 때 저장한 실제 STT 가설(줄 단위)로 대본의 L1 기대 판정이 몇 건 살아남는지. 엔진은 LLM 없이."""
import glob
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "back"))
from contracts.engine_contract import Utterance
from engine.adapters.pack_source.file import FilePackSource
from engine.build import build_engine
ROOT = Path(__file__).resolve().parents[5]; EXP = ROOT / "back/scripts/experiments/stt"
FILES = sorted(glob.glob(str(EXP / "qwen_asr/eval_*.json")) + glob.glob(str(EXP / "nemotron/*_eval.json")) + glob.glob(str(EXP / "elevenlabs/*_eval.json")))
engine = build_engine(FilePackSource(Path(sys.argv[1]) / "back/contracts/fixtures"))
PRESETS = ("preset-dep-a", "preset-loan-b")  # 음원·전사 실험이 있는 대본만
scripts = {p: json.load(open(ROOT / "assets/scenarios" / p / "script.json", encoding="utf-8")) for p in PRESETS}
PACKS = {p: scripts[p]["pack_version"] for p in PRESETS}  # 팩 버전의 진실 원천은 대본
grand_total = grand_kept = 0
for f in FILES:
    d = json.load(open(f)); total = kept = 0
    for preset, pv in PACKS.items():
        hyps = {l["id"]: l["hyp"] for l in d.get(preset, {}).get("lines", [])}
        if not hyps: continue
        pack = engine.load_pack(pv); state = engine.initial_state("S", pack, "text")
        for i, line in enumerate(scripts[preset]["lines"]):
            exp = [e for e in line.get("expect") or [] if e.startswith("verdict") and e.endswith("L1")]
            if not hyps.get(line["id"]): continue  # 전사가 없는 줄은 셈에서 뺀다
            u = Utterance(f"U-{i}", line["speaker"], hyps[line["id"]], i)
            r = engine.judge(u, pack, state); state = engine.apply(engine.observe(state, u), r)
            got = {(v.item_code, v.state) for v in r.verdicts if v.decided_by == "L1"}
            for e in exp:
                _, code, axis, st, _ = e.split(); total += 1; ok = (code, st) in got; kept += ok
                if not ok and "MISS" in sys.argv: print("   miss", line["id"], code, st, "|", hyps.get(line["id"], "")[:70])
    grand_total += total; grand_kept += kept
    print(f"{Path(f).parent.name}/{Path(f).name:40s} {kept:2d}/{total}")
print(f"합계 {grand_kept}/{grand_total}")
