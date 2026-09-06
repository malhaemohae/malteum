#!/usr/bin/env python3
"""화자 단계 테스트의 실측 픽스처(`tests/fixtures/sortformer_scenarios.json`)를 다시 잰다.

## 왜 있나

`tests/server/test_stt_speaker.py` 는 시연 음원을 Sortformer(화자 분리 모델) 로 실제 훑어
얻은 구간으로 재생해 화자 라벨을 대조한다. 그래서 그 픽스처는 **음원에 딸린 실측값**이고,
음원을 다시 만들면 같이 낡는다. 2026-09-06 에 TTS 공급자를 Typecast 로 옮겨 음원 네 개를
새로 뽑았더니 옛 구간이 새 `start_ms` 와 안 겹쳐 테스트가 32줄 중 25줄만 맞혔다. 그때
픽스처를 다시 잴 도구가 없어 손으로 옮겨야 했다. 이 스크립트가 그 자리를 메운다.

## 무엇을 채우나

    line_duration_ms   `clips/<id>.wav` 를 잰 줄 길이. `clips/` 는 커밋하지 않으므로
                       (SCRIPT.md 4.3) 테스트가 스스로 잴 수 없어 픽스처에 적어 둔다
    segments           사이드카에 음원을 흘려 받은 구간 목록. `"start end speaker_id"`(초)

## 실행 (back/ 에서)

    # 1) 줄 길이만. 사이드카가 필요 없다
    uv run python scripts/refresh_sortformer_fixture.py --durations

    # 2) 구간까지. 사이드카를 먼저 띄운다(sidecar/diarization/README.md)
    docker run -d -p 8300:8300 malteum-diar
    uv run python scripts/refresh_sortformer_fixture.py --durations --segments

`--speed` 를 올리면 빨리 감아 흘린다. 실시간(1.0) 이 아니면 라벨 지연은 못 재지만 구간
자체는 같게 나온다(사이드카가 청크 단위로만 보기 때문이다). 채점은 `diarization_check.py`
쪽이 하고 여기는 픽스처를 채우는 일만 한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

BACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACK))

from server.services.stt.diarization import SortformerDiarization  # noqa: E402

ROOT = BACK.parent
SCENARIOS = ROOT / "assets" / "scenarios"
FIXTURE = BACK / "tests" / "fixtures" / "sortformer_scenarios.json"
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
PUSH_MS = 100  # 계약의 audioFrame 과 같은 단위로 민다


def wav_ms(path: Path) -> int:
    with wave.open(str(path)) as f:
        if f.getnchannels() != 1 or f.getframerate() != SAMPLE_RATE or f.getsampwidth() != 2:
            raise SystemExit(f"{path}: 16kHz mono PCM16 이어야 합니다")
        return round(f.getnframes() / f.getframerate() * 1000)


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path)) as f:
        return f.readframes(f.getnframes())


def durations_of(preset_dir: Path) -> dict[str, int]:
    """대본 줄마다 그 클립의 길이. 클립이 하나라도 없으면 멈춘다. 반쪽 픽스처가 더 위험하다."""
    script = json.loads((preset_dir / "script.json").read_text(encoding="utf-8"))
    out: dict[str, int] = {}
    for line in script["lines"]:
        clip = preset_dir / "clips" / f"{line['id']}.wav"
        if not clip.exists():
            raise SystemExit(f"{clip} 이 없습니다. make_scenario_audio.py 로 클립을 먼저 만드세요")
        out[line["id"]] = wav_ms(clip)
    return out


async def segments_of(url: str, audio: Path, speed: float) -> list[str]:
    """음원을 흘려 최종 구간 목록을 픽스처 형식으로 받는다."""
    pcm = read_pcm(audio)
    source = SortformerDiarization(url)
    push_bytes = PUSH_MS * SAMPLE_RATE * BYTES_PER_SAMPLE // 1000
    started = time.perf_counter()
    try:
        for offset in range(0, len(pcm), push_bytes):
            await source.feed(pcm[offset : offset + push_bytes])
            behind = (offset + push_bytes) / (SAMPLE_RATE * BYTES_PER_SAMPLE) / speed
            await asyncio.sleep(max(0.0, behind - (time.perf_counter() - started)))
        # 마지막 청크(0.96초) 가 아직 안 돌아왔을 수 있다
        await asyncio.sleep(1.2 / speed)
        final = tuple(source.segments())
    finally:
        await source.aclose()
    return [f"{s.start_ms / 1000:.3f} {s.end_ms / 1000:.3f} {s.speaker_id}" for s in final]


async def main_async(args: argparse.Namespace) -> int:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    presets = args.scenario or sorted(
        d.name for d in SCENARIOS.iterdir() if (d / "audio.wav").exists()
    )
    for preset in presets:
        preset_dir = SCENARIOS / preset
        entry = fixture["presets"].setdefault(preset, {})
        if args.durations:
            got = durations_of(preset_dir)
            before = entry.get("line_duration_ms") or {}
            entry["line_duration_ms"] = got
            total = sum(got.values())
            moved = sum(1 for k, v in got.items() if before.get(k) != v)
            print(f"{preset}: 줄 {len(got)}개 합 {total / 1000:.1f}s (바뀐 줄 {moved})")
        if args.segments:
            segs = await segments_of(args.url, preset_dir / "audio.wav", args.speed)
            speakers = sorted({s.rsplit(" ", 1)[1] for s in segs})
            entry["segments"] = segs
            print(f"{preset}: 구간 {len(segs)}개 · 화자 번호 {speakers}")
        # 키 순서를 segments → line_duration_ms 로 고정해 diff 를 읽기 쉽게 둔다
        fixture["presets"][preset] = {
            "segments": entry.get("segments", []),
            "line_duration_ms": entry.get("line_duration_ms", {}),
        }
    FIXTURE.write_text(json.dumps(fixture, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"기록 → {FIXTURE.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="화자 단계 실측 픽스처 재측정")
    ap.add_argument("--url", default="ws://127.0.0.1:8300/ws")
    ap.add_argument("--scenario", action="append", default=None, help="기본: 음원이 있는 전부")
    ap.add_argument("--durations", action="store_true", help="clips 로 줄 길이를 다시 잰다")
    ap.add_argument("--segments", action="store_true", help="사이드카로 구간을 다시 잰다")
    ap.add_argument("--speed", type=float, default=1.0, help="1.0 이 실시간. 크게 하면 빨리 감기")
    args = ap.parse_args()
    if not (args.durations or args.segments):
        raise SystemExit("--durations 또는 --segments 중 하나는 주세요")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
