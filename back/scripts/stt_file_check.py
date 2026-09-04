"""발화 단위 전사 어댑터 실물 확인. 음원 한 편을 실시간 속도로 흘려 발화 유실을 잰다.

`diarization_check.py` 가 화자 분리만 보는 것과 달리, 여기서는 서버가 온프레미스
경로에서 실제로 쓰는 두 조각을 한 줄로 이어 확인한다.

    SortformerDiarization      사이드카(기본 8300)에 오디오를 흘려 화자 구간을 받는다
    SegmentedFileSttAdapter    닫힌 구간을 WAV 로 싸서 vLLM(기본 8100)에 전사를 시킨다

`SttSession.feed()` 와 같이 **같은 PCM 을 양쪽에 준다.** 두 조각이 서로 다른 시계를
보고 있으면(사이드카는 0.96초 청크 뒤에야 구간을 늘려 주고 어댑터는 받은 PCM 길이로
시각을 센다) 화자가 말하는 중에 구간이 닫혀 발화의 뒷부분이 통째로 사라지는데, 가짜
공급원으로 도는 단위 테스트로는 그 어긋남의 실제 크기를 알 수 없다. 그래서 대본 줄이
차지하는 시간 중 전사가 덮은 비율을 찍는다 — 유실이 있으면 이 값이 곧바로 떨어진다.

    줄 덮임      그 줄의 구간을 전사 하나 이상이 덮은 비율. 100 % 가 유실 없음이다
    온전한 줄    덮임이 `--intact`(기본 0.9) 이상인 줄. 뒷부분이 잘리면 여기서 빠진다

## 실행

    cd back
    .venv/bin/python scripts/stt_file_check.py --scenario preset-dep-a

먼저 사이드카(`sidecar/diarization/README.md`)와 Qwen3-ASR vLLM 서버
(`scripts/experiments/stt/qwen_vllm/HOWTO.md` 의 이미지로 `qwen-asr-serve`)를 띄운다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

BACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACK))

from scripts.diarization_check import (  # noqa: E402  sys.path 를 먼저 세운다
    BYTES_PER_SAMPLE,
    PUSH_MS,
    SAMPLE_RATE,
    lines_of,
    read_pcm,
)
from server.services.stt.base import Transcript  # noqa: E402
from server.services.stt.diarization import SortformerDiarization  # noqa: E402
from server.services.stt.openai_file import SegmentedFileSttAdapter  # noqa: E402


def covered_ratio(spans: list[tuple[int, int]], start_ms: int, end_ms: int) -> float:
    """그 줄의 구간을 전사들이 덮은 비율. 겹치는 전사가 있어도 두 번 세지 않는다."""
    if end_ms <= start_ms:
        return 0.0
    covered = 0
    reach = start_ms
    for s, e in sorted(spans):
        lo, hi = max(s, reach, start_ms), min(e, end_ms)
        if hi > lo:
            covered += hi - lo
            reach = hi
    return round(covered / (end_ms - start_ms), 3)


async def run_one(args: argparse.Namespace, audio: Path, lines: list[dict]) -> dict:
    """음원 하나를 실시간 속도로 흘리고 나온 전사를 모은다."""
    pcm = read_pcm(audio)
    source = SortformerDiarization(args.diarization_url)
    adapter = SegmentedFileSttAdapter(
        args.base_url, model=args.model, api_key=args.api_key or None, timeout_s=args.timeout
    )
    got: list[Transcript] = []
    started = time.perf_counter()

    async def on_transcript(t: Transcript) -> None:
        got.append(t)
        end_s = (t.start_ms + (t.duration_ms or 0)) / 1000
        print(
            f"  전사 {len(got):2d}  {t.start_ms / 1000:7.2f}~{end_s:7.2f}s  {t.speaker_id}"
            f"  (발화 끝에서 +{(time.perf_counter() - started) * args.speed - end_s:.1f}s)"
            f"  {t.text}",
            flush=True,
        )

    push_bytes = PUSH_MS * SAMPLE_RATE * BYTES_PER_SAMPLE // 1000
    stream = await adapter.open(on_transcript, tuple(args.keyterm), diarization=source)
    try:
        for offset in range(0, len(pcm), push_bytes):
            chunk = pcm[offset : offset + push_bytes]
            # SttSession.feed() 와 같은 순서다. 같은 PCM 이 양쪽에 간다
            await source.feed(chunk)
            await stream.send(chunk)
            behind = (offset + push_bytes) / (SAMPLE_RATE * BYTES_PER_SAMPLE) / args.speed
            await asyncio.sleep(max(0.0, behind - (time.perf_counter() - started)))
        # 마지막 청크가 아직 안 돌아왔을 수 있다. 청크 하나(0.96초)만 더 기다린다
        await asyncio.sleep(1.2 / args.speed)
        segments = source.segments()
        covered_ms = source.covered_ms
    finally:
        # 어댑터를 먼저 닫아야 마지막 구간이 전사되어 나간다
        await stream.aclose()
        await source.aclose()

    spans = [(t.start_ms, t.start_ms + (t.duration_ms or 0)) for t in got]
    per_line = [
        {
            "id": line["id"],
            "speaker": line["speaker"],
            "start_ms": line["start_ms"],
            "end_ms": line["end_ms"],
            "covered": covered_ratio(spans, line["start_ms"], line["end_ms"]),
            "text": line["text"],
        }
        for line in lines
    ]
    spoken_ms = sum(line["end_ms"] - line["start_ms"] for line in lines)
    filled_ms = sum(
        round(line["covered"] * (line["end_ms"] - line["start_ms"])) for line in per_line
    )
    return {
        "lines": len(lines),
        "transcripts": len(got),
        "intact_lines": sum(1 for line in per_line if line["covered"] >= args.intact),
        "covered_ratio": round(filled_ms / spoken_ms, 3) if spoken_ms else 0.0,
        "diarization_segments": len(segments),
        "diarization_covered_ms": covered_ms,
        "per_line": per_line,
        "utterances": [
            {
                "start_ms": t.start_ms,
                "duration_ms": t.duration_ms,
                "speaker_id": t.speaker_id,
                "text": t.text,
            }
            for t in got
        ],
    }


def script_of(scenarios: Path, preset: str) -> dict:
    return json.loads((scenarios / preset / "script.json").read_text(encoding="utf-8"))


def with_text(script: dict, lines: list[dict]) -> list[dict]:
    """`lines_of` 는 시각만 준다. 전사와 눈으로 대조하려면 대본 문장이 있어야 한다."""
    text = {line["id"]: line["text"] for line in script["lines"]}
    return [{**line, "text": text.get(line["id"], "")} for line in lines]


async def main_async(args: argparse.Namespace) -> int:
    scenarios = Path(args.scenarios)
    fixture = json.loads(
        (BACK / "tests" / "fixtures" / "sortformer_scenarios.json").read_text(encoding="utf-8")
    )
    report = {
        "base_url": args.base_url,
        "diarization_url": args.diarization_url,
        "model": args.model,
        "speed": args.speed,
        "intact": args.intact,
        "scenarios": {},
    }
    total_lines = total_intact = 0
    for preset in args.scenario:
        script = script_of(scenarios, preset)
        audio = scenarios / preset / script["audio"]["output"]
        if not audio.exists():
            raise SystemExit(f"음원이 없습니다: {audio}")
        lines = with_text(script, lines_of(scenarios, fixture, preset))
        print(f"== {preset}: 대본 {len(lines)}줄 · {audio}", flush=True)
        result = await run_one(args, audio, lines)
        report["scenarios"][preset] = result
        total_lines += result["lines"]
        total_intact += result["intact_lines"]
        print(
            f"{preset}: 줄 {result['lines']} · 전사 {result['transcripts']}"
            f" · 온전한 줄 {result['intact_lines']}/{result['lines']}"
            f" · 줄 덮임 {result['covered_ratio'] * 100:.1f} %"
            f" · 구간 {result['diarization_segments']}",
            flush=True,
        )
        for line in result["per_line"]:
            mark = "  " if line["covered"] >= args.intact else "!!"
            print(f"  {mark} {line['id']} 덮임 {line['covered'] * 100:5.1f} %  {line['text']}")
    report["total"] = {"lines": total_lines, "intact": total_intact}
    print(f"합계: 온전한 줄 {total_intact}/{total_lines}", flush=True)
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"기록: {args.out}")
    return 0 if total_intact == total_lines else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    parser.add_argument("--diarization-url", default="ws://127.0.0.1:8300/ws")
    parser.add_argument("--model", default="Qwen/Qwen3-ASR-1.7B")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--scenarios", default=str(BACK.parent / "assets" / "scenarios"))
    parser.add_argument("--scenario", action="append", default=None, help="기본: preset-dep-a")
    parser.add_argument("--keyterm", action="append", default=[], help="prompt 로 넘길 용어")
    parser.add_argument(
        "--speed", type=float, default=1.0, help="1.0 이 실시간. 크게 하면 빨리 감기"
    )
    parser.add_argument(
        "--intact", type=float, default=0.9, help="이 비율 이상 덮인 줄을 온전한 줄로 센다"
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="전사 한 번의 상한(초)")
    parser.add_argument("--out", default=None, help="JSON 보고서를 남길 경로")
    args = parser.parse_args()
    args.scenario = args.scenario or ["preset-dep-a"]
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
