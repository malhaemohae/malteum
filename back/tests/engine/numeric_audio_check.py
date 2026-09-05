"""저장된 로컬 ASR 전사와 실제 E2E 발화를 같은 순서로 L1에 재생한다. 외부 호출 없음.

back/에서 실행:
    uv run python tests/engine/numeric_audio_check.py --engine-root .. --output result.json
    uv run python tests/engine/numeric_audio_check.py --engine-root /tmp/baseline \
        --events recording.json --output before.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", type=Path, required=True)
    parser.add_argument("--events", type=Path, nargs="*", default=[])
    parser.add_argument("--split-sentences", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.engine_root.resolve() / "back"))

    from contracts.engine_contract import Utterance
    from engine.adapters.pack_source.file import FilePackSource
    from engine.build import build_engine
    from engine.tiers.l1.numeric import said_numbers
    from server.services.stt.assembler import utterances as split_sentences

    engine = build_engine(FilePackSource(ROOT / "back/contracts/fixtures"))
    rows = []

    def replay(source, pack_version, utterances):
        pack = engine.load_pack(pack_version)
        state = engine.initial_state("S-NUMERIC-AUDIO", pack, "replay")
        for utterance, expected in utterances:
            result = engine.judge(utterance, pack, state)
            state = engine.apply(engine.observe(state, utterance), result)
            rows.append(
                {
                    "source": source,
                    "id": utterance.utterance_id,
                    "text": utterance.text,
                    "numbers": said_numbers(utterance.text),
                    "expected": expected,
                    "verdicts": [asdict(v) for v in result.verdicts],
                    "numeric_alerts": [
                        asdict(a) for a in result.alerts if a.alert_type == "number_mismatch"
                    ],
                }
            )

    experiments = ROOT / "back/scripts/experiments/stt"
    for path in sorted(
        [*experiments.glob("qwen_asr/eval_*.json"), *experiments.glob("nemotron/*_eval.json")]
    ):
        data = json.loads(path.read_text())
        for preset in ("preset-dep-a", "preset-loan-b"):
            hypotheses = {line["id"]: line["hyp"] for line in data.get(preset, {}).get("lines", [])}
            if not hypotheses:
                continue
            script = json.loads((ROOT / "assets/scenarios" / preset / "script.json").read_text())
            replay(
                str(path.relative_to(experiments)),
                script["pack_version"],
                [
                    (
                        Utterance(
                            f"{line['id']}/{i}" if args.split_sentences else line["id"],
                            line["speaker"],
                            text,
                            line["start_ms"],
                        ),
                        line.get("expect", []),
                    )
                    for line in script["lines"]
                    if hypotheses.get(line["id"])
                    for i, text in enumerate(
                        split_sentences(hypotheses[line["id"]])
                        if args.split_sentences
                        else [hypotheses[line["id"]]]
                    )
                ],
            )
    for path in args.events:
        record = json.loads(path.read_text())
        started = next(e for e in record["events"] if e["kind"] == "session_started")
        replay(
            str(path),
            started["pack_version"],
            [
                (Utterance(utterance_id=e["event_id"], **e["utterance"]), [])
                for e in record["events"]
                if e["kind"] == "utterance"
            ],
        )
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(rows)} utterances -> {args.output}")


if __name__ == "__main__":
    main()
