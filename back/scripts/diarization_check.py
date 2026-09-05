"""화자 분리 사이드카 실물 확인. 음원을 실시간 속도로 흘려 줄 단위 정확도와 라벨 지연을 잰다.

서버가 실제로 쓰는 클라이언트(`server/services/stt/diarization.py` 의
`SortformerDiarization`)를 그대로 써서, 사이드카와 클라이언트를 한 번에 확인한다.
가짜 WebSocket 으로 도는 단위 테스트(`tests/server/test_stt_speaker.py`)가 못 잡는
것 — 프레임 크기, 시각의 원점, 실시간 여유 — 이 여기서 드러난다.

    정확도    줄마다 그 구간과 가장 많이 겹치는 화자 번호를 고르고, 번호 ↔ teller·
              customer 를 1:1 로 가장 잘 맞는 쪽으로 대응시켜 맞은 줄을 센다
    라벨 지연 그 줄이 끝난 뒤, **그 줄의 끝까지 실제로 본** 구간 목록이 돌아와 화자
              번호가 붙기까지의 시간. 실시간 재생이라 청크가 차는 시간·사이드카 처리
              시간·왕복이 모두 들어간 값이다

"줄의 끝까지 실제로 봤는가" 를 사이드카가 함께 주는 `covered_ms` 로 가린다. 이것을 안
보면 지연이 실제보다 훨씬 짧게 나온다 — Sortformer 는 줄이 끝나기 한참 전부터 그 줄의
앞부분에 이미 화자를 붙여 두므로, "겹치는 화자가 있나" 만 보면 줄이 끝나는 순간 곧바로
답이 있는 것처럼 보인다. 청크 축소 실험(`scripts/experiments/stt/sortformer_chunk/
RESULT.md`)이 잰 값과 같은 정의여야 두 값을 나란히 놓을 수 있다.

AC-4 의 지연 측정 도구가 이 스크립트다.

## 실행

    cd back
    .venv/bin/python scripts/diarization_check.py --url ws://127.0.0.1:8300/ws

사이드카를 먼저 띄운다(`sidecar/diarization/README.md`). 줄 길이는 대본 조각
(`clips/<id>.wav`)을 커밋하지 않기로 했으므로 테스트 픽스처
`tests/fixtures/sortformer_scenarios.json` 에서 읽는다.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import sys
import time
import wave
from pathlib import Path

BACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACK))

from server.services.stt.diarization import (  # noqa: E402  sys.path 를 먼저 세운다
    SortformerDiarization,
    SpeakerSegment,
)

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
PUSH_MS = 100  # 계약의 audioFrame 과 같은 단위로 민다


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path)) as f:
        if f.getnchannels() != 1 or f.getframerate() != SAMPLE_RATE or f.getsampwidth() != 2:
            raise SystemExit(f"{path}: 16kHz mono PCM16 이어야 합니다")
        return f.readframes(f.getnframes())


def lines_of(scenarios: Path, fixture: dict, preset: str) -> list[dict]:
    script = json.loads((scenarios / preset / "script.json").read_text(encoding="utf-8"))
    durations = fixture["presets"][preset]["line_duration_ms"]
    return [
        {
            "id": line["id"],
            "speaker": line["speaker"],
            "start_ms": line["start_ms"],
            "end_ms": line["start_ms"] + durations[line["id"]],
        }
        for line in script["lines"]
    ]


def overlapping(segments, start_ms: int, end_ms: int) -> str | None:
    """그 줄 구간과 가장 많이 겹치는 화자 번호. 실험의 채점 방식과 같다."""
    overlap: dict[str, int] = {}
    for s in segments:
        shared = min(s.end_ms, end_ms) - max(s.start_ms, start_ms)
        if shared > 0:
            overlap[s.speaker_id] = overlap.get(s.speaker_id, 0) + shared
    return max(overlap, key=lambda sid: overlap[sid]) if overlap else None


def best_mapping(picked: list[str | None], truth: list[str]) -> tuple[dict[str, str], int]:
    """번호 → 역할 대응을 정확도가 최대가 되도록 고른다. 번호가 사람보다 많을 수 있다."""
    numbers = sorted({p for p in picked if p})
    roles = ("teller", "customer")
    best: tuple[dict[str, str], int] = ({}, -1)
    for assignment in itertools.product(roles, repeat=len(numbers)):
        mapping = dict(zip(numbers, assignment, strict=True))
        hits = sum(1 for p, t in zip(picked, truth, strict=True) if p and mapping[p] == t)
        if hits > best[1]:
            best = (mapping, hits)
    return best


async def run_one(url: str, audio: Path, lines: list[dict], speed: float) -> dict:
    """음원 하나를 실시간 속도로 흘린다. 줄이 끝난 뒤 라벨이 처음 붙는 시각을 잰다."""
    pcm = read_pcm(audio)
    source = SortformerDiarization(url)
    push_bytes = PUSH_MS * SAMPLE_RATE * BYTES_PER_SAMPLE // 1000
    first_seen: dict[str, tuple[float, str]] = {}  # id -> (지연 초, 그때의 번호)
    started = time.perf_counter()
    try:
        for offset in range(0, len(pcm), push_bytes):
            await source.feed(pcm[offset : offset + push_bytes])
            elapsed_ms = (time.perf_counter() - started) * 1000 * speed
            segments = source.segments()
            for line in lines:
                # 그 줄의 끝까지 실제로 본 목록이라야 센다. 안 그러면 줄이 끝나기 전에
                # 이미 붙어 있던 앞부분 라벨을 지연 0 으로 세게 된다
                if line["id"] in first_seen or source.covered_ms < line["end_ms"]:
                    continue
                picked = overlapping(segments, line["start_ms"], line["end_ms"])
                if picked is not None:
                    first_seen[line["id"]] = ((elapsed_ms - line["end_ms"]) / 1000, picked)
            # 남은 시간만큼 자면 실시간 재생이 된다. 처리가 밀리면 자지 않는다
            behind = (offset + push_bytes) / (SAMPLE_RATE * BYTES_PER_SAMPLE) / speed
            await asyncio.sleep(max(0.0, behind - (time.perf_counter() - started)))
        # 마지막 청크가 아직 안 돌아왔을 수 있다. 청크 하나(0.96초)만 더 기다린다
        await asyncio.sleep(1.2 / speed)
        final: tuple[SpeakerSegment, ...] = tuple(source.segments())
    finally:
        await source.aclose()

    truth = [line["speaker"] for line in lines]
    picked_final = [overlapping(final, line["start_ms"], line["end_ms"]) for line in lines]
    mapping, hits = best_mapping(picked_final, truth)
    online = [first_seen.get(line["id"], (None, None))[1] for line in lines]
    online_hits = sum(1 for p, t in zip(online, truth, strict=True) if p and mapping.get(p) == t)
    delays = [d for d, _ in first_seen.values()]
    return {
        "lines": len(lines),
        "final_hits": hits,
        "online_hits": online_hits,
        "labelled": len(first_seen),
        "delay_mean_s": round(sum(delays) / len(delays), 3) if delays else None,
        "delay_max_s": round(max(delays), 3) if delays else None,
        "speakers": sorted({s.speaker_id for s in final}),
        "mapping": mapping,
        "segments": len(final),
        "per_line": [
            {
                "id": line["id"],
                "truth": line["speaker"],
                "final": picked_final[i],
                "online": online[i],
                "delay_s": first_seen.get(line["id"], (None, None))[0],
            }
            for i, line in enumerate(lines)
        ],
    }


async def main_async(args: argparse.Namespace) -> int:
    fixture = json.loads(
        (BACK / "tests" / "fixtures" / "sortformer_scenarios.json").read_text(encoding="utf-8")
    )
    report = {"url": args.url, "push_ms": PUSH_MS, "speed": args.speed, "scenarios": {}}
    total_lines = total_final = total_online = 0
    for preset in args.scenario:
        audio = Path(args.scenarios) / preset / "audio.wav"
        if not audio.exists():
            raise SystemExit(f"음원이 없습니다: {audio}")
        result = await run_one(
            args.url, audio, lines_of(Path(args.scenarios), fixture, preset), args.speed
        )
        report["scenarios"][preset] = result
        total_lines += result["lines"]
        total_final += result["final_hits"]
        total_online += result["online_hits"]
        print(
            f"{preset}: 최종 {result['final_hits']}/{result['lines']}"
            f" · 온라인 {result['online_hits']}/{result['lines']}"
            f" · 라벨 지연 평균 {result['delay_mean_s']}s 최대 {result['delay_max_s']}s"
            f" · 화자 {result['speakers']} · 구간 {result['segments']}",
            flush=True,
        )
    report["total"] = {"lines": total_lines, "final": total_final, "online": total_online}
    print(f"합계: 최종 {total_final}/{total_lines} · 온라인 {total_online}/{total_lines}")
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"기록: {args.out}")
    return 0 if total_final == total_lines else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8300/ws")
    parser.add_argument("--scenarios", default=str(BACK.parent / "assets" / "scenarios"))
    parser.add_argument(
        "--scenario", action="append", default=None, help="기본: preset-dep-a, preset-loan-b"
    )
    parser.add_argument(
        "--speed", type=float, default=1.0, help="1.0 이 실시간. 크게 하면 빨리 감기"
    )
    parser.add_argument("--out", default=None, help="JSON 보고서를 남길 경로")
    args = parser.parse_args()
    args.scenario = args.scenario or ["preset-dep-a", "preset-loan-b"]
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
