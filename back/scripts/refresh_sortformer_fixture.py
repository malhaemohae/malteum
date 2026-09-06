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
    uv run python scripts/refresh_sortformer_fixture.py --durations --segments --speed 4

실시간으로 흘리면 네 편에 8분쯤 걸린다. 사이드카는 청크 하나(0.96초)를 0.11초에 처리하므로
(sidecar/diarization/README.md DEC-6 실측) 4배속에도 밀리지 않고 2분에 끝난다. 구간 시각은
사이드카가 청크 수로 세므로 배속과 무관하다. 8배를 넘기면 `FLUSH_WAIT_S` 가 꼬리를 못 덮는다.

채점은 `diarization_check.py` 쪽이 하고 여기는 픽스처를 채우는 일만 한다.

두 플래그는 되도록 함께 준다. 한쪽만 주면 안 잰 쪽은 있던 값을 그대로 두지만, 픽스처에
아직 없는 프리셋이면 그 자리가 비어 테스트가 이유 없는 KeyError 로 죽는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

BACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACK))

# 규격 상수와 WAV 읽기는 `diarization_check.py` 가 집이다. `stt_file_check.py` 도 거기서
# 가져다 쓴다. 손으로 다시 적으면 16kHz·mono·PCM16 검사가 빠지기 쉽다. 실제로 이 파일의
# 첫 판이 그랬고, 44.1kHz 음원을 그대로 사이드카에 밀어 넣을 수 있었다
from scripts.diarization_check import (  # noqa: E402  sys.path 를 먼저 세운다
    BYTES_PER_SAMPLE,
    PUSH_MS,
    SAMPLE_RATE,
    read_pcm,
)
from server.services.stt.diarization import SortformerDiarization  # noqa: E402

ROOT = BACK.parent
SCENARIOS = ROOT / "assets" / "scenarios"
FIXTURE = BACK / "tests" / "fixtures" / "sortformer_scenarios.json"
# 마지막 청크가 돌아오기를 기다리는 시간. 사이드카가 실제로 추론하는 벽시계 시간이라
# `--speed` 로 빨리 감아도 줄지 않는다(청크 0.96초 + 왕복)
FLUSH_WAIT_S = 1.2


def wav_ms(path: Path) -> int:
    """그 WAV 의 길이(밀리초). 규격 검사는 `read_pcm` 이 함께 한다."""
    return len(read_pcm(path)) * 1000 // (SAMPLE_RATE * BYTES_PER_SAMPLE)


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
    """음원을 흘려 최종 구간 목록을 픽스처 형식으로 받는다.

    **빈 목록이면 예외를 던진다.** `SortformerDiarization.feed` 는 사이드카에 못 붙어도 경고
    한 줄만 남기고 조용히 넘어가도록 만들어져 있다(실제 상담에서 화자 분리가 죽었다고 상담을
    멈출 수는 없기 때문). 그 설계를 그대로 두고 여기서 결과를 검사하지 않으면, 사이드카를
    안 띄우고 `--segments` 를 돌린 사람이 네 프리셋의 실측 구간을 통째로 빈 배열로 덮어쓴다.
    다시 재려면 Docker 이미지부터 세워야 하는 데이터다.
    """
    pcm = read_pcm(audio)
    source = SortformerDiarization(url)
    push_bytes = PUSH_MS * SAMPLE_RATE * BYTES_PER_SAMPLE // 1000
    started = time.perf_counter()
    try:
        for offset in range(0, len(pcm), push_bytes):
            await source.feed(pcm[offset : offset + push_bytes])
            behind = (offset + push_bytes) / (SAMPLE_RATE * BYTES_PER_SAMPLE) / speed
            await asyncio.sleep(max(0.0, behind - (time.perf_counter() - started)))
        # 마지막 청크(0.96초) 가 아직 안 돌아왔을 수 있다. 이 기다림은 사이드카가 추론하는
        # 실제 시간이라 재생을 빨리 감아도 줄지 않는다. `speed` 로 나누면 빨리 감기에서
        # 꼬리 구간이 빠진 채로 기록된다
        await asyncio.sleep(FLUSH_WAIT_S)
        final = tuple(source.segments())
    finally:
        await source.aclose()
    if not final:
        raise SystemExit(
            f"{audio.name}: 구간을 하나도 못 받았습니다. 사이드카({url})가 떠 있는지 "
            "확인하세요(sidecar/diarization/README.md). 픽스처는 건드리지 않았습니다"
        )
    return [f"{s.start_ms / 1000:.3f} {s.end_ms / 1000:.3f} {s.speaker_id}" for s in final]


def check_sidecar(url: str) -> None:
    """스트리밍을 시작하기 전에 사이드카가 떠 있는지 본다.

    `feed` 는 못 붙어도 조용히 넘어가므로(실제 상담을 멈출 수 없어서 그렇게 만든 설계),
    이 확인이 없으면 프리셋 하나를 통째로 흘려보낸 **뒤에야** 빈 목록 가드가 발동한다.
    dep-a 한 편이 114초라 오타 하나에 2분을 버린다. 여기서 5초 안에 끊는다.
    """
    health = url.replace("ws://", "http://").replace("wss://", "https://")
    health = health.rsplit("/", 1)[0] + "/health"
    try:
        resp = httpx.get(health, timeout=5)
    except httpx.HTTPError as e:
        raise SystemExit(
            f"화자 분리 사이드카에 못 붙었습니다({health}): {e}\n"
            "  docker start malteum-diar-run  또는 sidecar/diarization/README.md 참고"
        ) from e
    if resp.status_code != 200:
        raise SystemExit(f"사이드카가 {resp.status_code} 를 냈습니다({health})")


async def main_async(args: argparse.Namespace) -> int:
    if args.segments:
        check_sidecar(args.url)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    presets = args.scenario or sorted(
        d.name for d in SCENARIOS.iterdir() if (d / "audio.wav").exists()
    )
    for preset in presets:
        preset_dir = SCENARIOS / preset
        # 키 순서를 segments → line_duration_ms 로 고정해 diff 를 읽기 쉽게 둔다. 새 프리셋도
        # 그 순서로 심어 두면 아래는 제자리 대입만 하면 되고, 이번에 안 잰 쪽은 저절로 남는다
        entry = fixture["presets"].setdefault(preset, {"segments": [], "line_duration_ms": {}})
        if args.durations:
            got = durations_of(preset_dir)
            moved = sum(1 for k, v in got.items() if entry["line_duration_ms"].get(k) != v)
            entry["line_duration_ms"] = got
            print(f"{preset}: 줄 {len(got)}개 합 {sum(got.values()) / 1000:.1f}s (바뀐 줄 {moved})")
        if args.segments:
            segs = await segments_of(args.url, preset_dir / "audio.wav", args.speed)
            entry["segments"] = segs
            speakers = sorted({s.rsplit(" ", 1)[1] for s in segs})
            print(f"{preset}: 구간 {len(segs)}개 · 화자 번호 {speakers}")
        # 한쪽 플래그만 주고 돌렸는데 다른 쪽이 빈 채로 남으면 테스트는 KeyError 나 화자 없음
        # 으로 죽으면서 이유를 말해 주지 않는다. 여기서 미리 말해 준다
        for name in ("segments", "line_duration_ms"):
            if not entry[name]:
                print(f"  주의 {preset}: {name} 가 비었습니다. 두 플래그를 함께 주세요")
    FIXTURE.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
