#!/usr/bin/env python3
"""시연 대본(`assets/scenarios/<preset>/script.json`)을 ElevenLabs TTS 로 읽어 `audio.wav` 를
만든다.

SCRIPT.md 4.3 의 제작·조립 지침을 그대로 따른다.
    클립   줄 하나에 파일 하나(`clips/<id>.wav`). `tts_text` 가 있으면 그것을, 없으면 `text`
    음성   `speakers.<role>.tts` 의 voice_id·speed. 두 시나리오의 은행원은 같은 음성
    조립   클립을 앞 클립 끝 + `gap_ms` 에 이어 놓는다. 앞 줄이 경보·카드(`expect` 의
           alert·assist)를 내면 심사위원이 읽을 시간으로 `alert_gap_ms` 를 둔다. 첫 줄은 `start_ms`
    시각   `--write-start` 가 그렇게 놓인 실제 시각을 `script.json` 의 `start_ms`·`duration_ms` 에
           되쓴다. `gen_scenario_trace.py` 가 그 값을 fixture 이벤트 시각으로 쓰므로 되쓴 뒤
           fixture 를 다시 만든다
    규격   16kHz · mono · PCM16. `pcm_16000` 으로 받으므로 리샘플링·ffmpeg 가 필요 없다

클립은 캐시다. 이미 있는 `clips/<id>.wav` 는 다시 만들지 않는다(크레딧 절약). 대사를 고쳤으면
그 줄의 클립을 지우거나 `--force` 로 돌린다. `--assemble-only` 는 API 를 부르지 않는다.

사용 (back/ 에서)
    uv run python scripts/make_scenario_audio.py                 # 두 프리셋 전부
    uv run python scripts/make_scenario_audio.py preset-dep-a
    uv run python scripts/make_scenario_audio.py --assemble-only
    uv run python scripts/make_scenario_audio.py --write-start   # start_ms 되쓰기 → fixture 재생성
    ELEVENLABS_API_KEY 를 환경변수 또는 레포 루트 .env 에서 읽는다.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import wave
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "assets" / "scenarios"
API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def load_api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for raw in env.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line.startswith("ELEVENLABS_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'\"")
                    break
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY 가 없습니다. 환경변수 또는 루트 .env 를 확인하세요.")
    return key


def synthesize(client: httpx.Client, model: str, tts: dict, text: str) -> bytes:
    """pcm_16000(16kHz mono s16le, 헤더 없음) 바이트를 돌려준다."""
    resp = client.post(
        API.format(voice_id=tts["voice_id"]),
        params={"output_format": "pcm_16000"},
        json={
            "text": text,
            "model_id": model,
            "language_code": "ko",
            "voice_settings": {
                "stability": tts.get("stability", 0.4),
                "similarity_boost": tts.get("similarity_boost", 0.75),
                "style": tts.get("style", 0.35),
                "speed": tts.get("speed", 1.0),
            },
        },
    )
    if resp.status_code != 200:
        raise SystemExit(f"ElevenLabs {resp.status_code}: {resp.text[:300]}")
    return resp.content


def write_wav(path: Path, pcm: bytes, rate: int, channels: int, width: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)


def read_pcm(path: Path, rate: int, channels: int, width: int) -> bytes:
    with wave.open(str(path), "rb") as w:
        got = (w.getframerate(), w.getnchannels(), w.getsampwidth())
        if got != (rate, channels, width):
            raise SystemExit(f"{path.name} 규격 불일치 {got} != {(rate, channels, width)}")
        return w.readframes(w.getnframes())


def build(preset_dir: Path, *, api_key: str | None, force: bool, write_start: bool) -> None:
    script = json.loads((preset_dir / "script.json").read_text(encoding="utf-8"))
    audio = script["audio"]
    rate, channels, width = audio["sample_rate"], audio["channels"], audio["sample_width_bytes"]
    bytes_per_ms = rate * channels * width // 1000
    model = audio.get("tts_model", "eleven_multilingual_v2")
    clips_dir = preset_dir / "clips"
    clips_dir.mkdir(exist_ok=True)

    # 1) 클립
    client = httpx.Client(headers={"xi-api-key": api_key}, timeout=120) if api_key else None
    for line in script["lines"]:
        clip = clips_dir / f"{line['id']}.wav"
        if clip.exists() and not force:
            continue
        if client is None:
            raise SystemExit(f"클립이 없는데 --assemble-only 입니다: {clip}")
        tts = script["speakers"][line["speaker"]]["tts"]
        text = line.get("tts_text") or line["text"]
        pcm = synthesize(client, model, tts, text)
        write_wav(clip, pcm, rate, channels, width)
        secs = len(pcm) // bytes_per_ms / 1000
        print(f"  {line['id']} {line['speaker']:8s} {secs:5.1f}s  {text[:30]}")

    # 2) 조립: 이어 붙이기. 경보·카드 줄 뒤에만 길게 쉰다
    gap = audio.get("gap_ms", 1200)
    alert_gap = audio.get("alert_gap_ms", 4000)
    out = io.BytesIO()
    cursor_ms = 0
    prev_alerted = False
    timeline: list[tuple[str, int, int]] = []
    for i, line in enumerate(script["lines"]):
        pcm = read_pcm(clips_dir / f"{line['id']}.wav", rate, channels, width)
        want = line["start_ms"] if i == 0 else cursor_ms + (alert_gap if prev_alerted else gap)
        out.write(b"\x00" * ((want - cursor_ms) * bytes_per_ms))
        out.write(pcm)
        dur = len(pcm) // bytes_per_ms
        cursor_ms = want + dur
        timeline.append((line["id"], want, dur))
        prev_alerted = _alerts(line)
    cursor_ms += gap
    out.write(b"\x00" * (gap * bytes_per_ms))

    target = preset_dir / audio["output"]
    write_wav(target, out.getvalue(), rate, channels, width)
    print(f"→ {target.relative_to(ROOT)}  {cursor_ms / 1000:.1f}s")
    for lid, start, dur in timeline:
        print(f"    {lid} {start / 1000:6.1f}s +{dur / 1000:4.1f}s")

    if write_start:
        _write_start(preset_dir / "script.json", timeline, cursor_ms)


def _alerts(line: dict) -> bool:
    """이 줄이 화면에 경보 카드나 조력 카드를 띄우는가. `expect` 의 `alert <type>`·`assist <type>`.
    서버(`services/presets.py`)가 읽는 형식과 같다. `alert 없음` 은 제외."""
    for e in line.get("expect", []):
        tok = e.split()
        if len(tok) >= 2 and tok[0] in ("alert", "assist") and tok[1] != "없음":
            return True
    return False


def _write_start(path: Path, timeline: list[tuple[str, int, int]], total_ms: int) -> None:
    """포맷을 건드리지 않고 각 줄의 start_ms 와 duration_ms 만 바꿔 쓴다."""
    text = path.read_text(encoding="utf-8")
    for lid, start, _ in timeline:
        text, n = re.subn(rf'("id": "{lid}", "start_ms": )\d+', rf"\g<1>{start}", text, count=1)
        if n != 1:
            raise SystemExit(f"{path.name}: {lid} 의 start_ms 를 못 찾았습니다")
    text = re.sub(r'("duration_ms": )\d+', rf"\g<1>{total_ms}", text, count=1)
    path.write_text(text, encoding="utf-8")
    print(f"  start_ms·duration_ms 되씀 → {path.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="시연 대본 → ElevenLabs TTS → audio.wav")
    ap.add_argument("preset", nargs="*", help="preset_id. 없으면 전부")
    ap.add_argument("--force", action="store_true", help="캐시된 클립도 다시 만든다")
    ap.add_argument("--assemble-only", action="store_true", help="API 호출 없이 클립만 조립")
    ap.add_argument("--write-start", action="store_true", help="조립 시각을 script.json 에 되쓴다")
    args = ap.parse_args()

    presets = [SCENARIOS / p for p in args.preset] or sorted(
        d for d in SCENARIOS.iterdir() if (d / "script.json").exists()
    )
    api_key = None if args.assemble_only else load_api_key()
    for d in presets:
        print(f"[{d.name}]")
        build(d, api_key=api_key, force=args.force, write_start=args.write_start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
