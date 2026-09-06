#!/usr/bin/env python3
"""시연 대본(`assets/scenarios/<preset>/script.json`)을 Typecast TTS 로 읽어 `audio.wav` 를
만든다.

SCRIPT.md 4.3 의 제작·조립 지침을 그대로 따른다.
    클립   줄 하나에 파일 하나(`clips/<id>.wav`). `tts_text` 가 있으면 그것을, 없으면 `text`
    음성   `speakers.<role>.tts` 의 voice_id·tempo·pitch. 네 시나리오의 은행원은 같은 음성
    억양   앞뒤 줄의 대사를 `prompt.previous_text`·`next_text` 로 함께 준다. Typecast 의
           smart 감정이 그 문맥으로 억양을 정하므로 혼잣말이 아니라 대화로 들린다
    조립   앞 클립 끝에 이어 놓되 쉬는 길이를 줄 성격마다 달리한다(아래 `gap_for`)
    시각   `--write-start` 가 그렇게 놓인 실제 시각을 `script.json` 의 `start_ms`·`duration_ms` 에
           되쓴다. `gen_scenario_trace.py` 가 그 값을 fixture 이벤트 시각으로 쓰므로 되쓴 뒤
           fixture 를 다시 만든다
    규격   16kHz · mono · PCM16. Typecast 는 44.1kHz WAV 로만 주므로 받아서 내려 리샘플한다

## 쉬는 길이를 줄마다 달리하는 이유

모든 자리를 같은 1.2초로 두면 사람이 아니라 자동응답기로 들린다. 실제 상담은 받아치는
자리가 짧고 소화할 것이 많은 자리가 길다. 그래서 `gap_for` 가 앞 줄의 성격으로 고른다.

    같은 화자가 이어 말함   `same_speaker_gap_ms`(0.78초). 한 사람이 문장을 잇는 자리라
                            화자 분리가 가를 필요가 없다
    앞 줄이 경보·카드를 냄  `alert_gap_ms`(2.2초). 심사위원이 카드를 읽을 시간
    앞 줄이 짧은 질문       `question_gap_ms`(1.05초). 묻는 말은 빨리 받는다
    앞 줄이 긴 설명         `long_gap_ms`(1.75초). 들은 쪽이 소화할 틈
    그 밖                   `gap_ms`(1.3초)

여기에 줄 id 로 정한 지터(`jitter_ms`, ±0.12초)를 더해 같은 값이 반복되지 않게 한다. 난수가
아니라 id 의 해시라서 몇 번을 돌려도 같은 파일이 나온다.

## 지터가 뚫지 못하는 두 하한

둘 다 취향이 아니라 파이프라인이 의존하는 값이다. 그래서 지터를 더한 뒤 클램프한다.

    화자가 바뀌는 자리   `min_gap_ms`(1초). `speaker.py` 의 `NEAREST_GAP_MS` 가 같은 1초여서
                         (그보다 가까우면 옆 화자의 구간을 끌어온다) 깨면 두 사람의 말이 한
                         발화로 붙거나 화자가 뒤섞인다
    같은 화자가 이어 말함 `same_speaker_min_gap_ms`(0.65초). `openai_file.py` 의
                         `SEGMENT_GAP_MS`(0.6초) 보다 짧으면 그 경로에서 발화가 닫히지 않고
                         다음 구간과 붙는다. 같은 사람이라 화자가 섞이지는 않지만, 두 문장이
                         한 발화로 합쳐지면 줄 단위로 걸어 둔 기대 판정과 어긋난다

처음 판에는 이 두 번째 하한이 없어 지터가 0.7초를 0.581초까지 끌어내렸다(dep-d D08→D09).
조립 전 드라이런에서 잡았다.

클립은 캐시다. 이미 있는 `clips/<id>.wav` 는 다시 만들지 않는다(크레딧 절약). 대사를 고쳤으면
그 줄의 클립을 지우거나 `--force` 로 돌린다. `--assemble-only` 는 API 를 부르지 않는다.

사용 (back/ 에서)
    uv run python scripts/make_scenario_audio.py                 # 네 프리셋 전부
    uv run python scripts/make_scenario_audio.py preset-dep-a
    uv run python scripts/make_scenario_audio.py --assemble-only # 조립만 다시(크레딧 안 씀)
    uv run python scripts/make_scenario_audio.py --write-start   # start_ms 되쓰기 → fixture 재생성
    TYPECAST_API_KEY 를 환경변수 또는 레포 루트 .env 에서 읽는다.
"""

from __future__ import annotations

import argparse
import audioop  # 3.13 에서 빠진다. 이 저장소는 3.12 고정(pyproject requires-python)
import hashlib
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
API = "https://api.typecast.ai/v1/text-to-speech"


def load_api_key() -> str:
    key = os.environ.get("TYPECAST_API_KEY")
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for raw in env.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line.startswith("TYPECAST_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'\"")
                    break
    if not key:
        raise SystemExit("TYPECAST_API_KEY 가 없습니다. 환경변수 또는 루트 .env 를 확인하세요.")
    return key


def line_text(line: dict) -> str:
    """TTS 에 넣을 문장. 숫자·단위를 읽는 법이 다른 줄은 `tts_text` 를 따로 적어 둔다."""
    return line.get("tts_text") or line["text"]


def synthesize(
    client: httpx.Client, model: str, tts: dict, text: str, prev: str, nxt: str
) -> bytes:
    """Typecast 가 준 WAV 바이트를 그대로 돌려준다.

    `prompt` 의 smart 감정은 앞뒤 대사를 보고 억양을 정한다. 이 값이 혼잣말이 아니라 대화로
    들리게 하는 가장 큰 요인이다.
    """
    prompt: dict = {"emotion_type": "smart"}
    if prev:
        prompt["previous_text"] = prev
    if nxt:
        prompt["next_text"] = nxt
    body = {
        "voice_id": tts["voice_id"],
        "text": text,
        "model": model,
        "language": "kor",
        "prompt": prompt,
        "output": {
            "audio_format": "wav",
            "volume": tts.get("volume", 100),
            "audio_pitch": tts.get("pitch", 0),
            "audio_tempo": tts.get("tempo", 1.0),
        },
        # 같은 대사를 다시 돌려도 같은 소리가 나오게 고정한다
        "seed": int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big"),
    }
    resp = client.post(API, json=body)
    if resp.status_code != 200:
        raise SystemExit(f"Typecast {resp.status_code}: {resp.text[:300]}")
    return resp.content


def to_pcm(wav_bytes: bytes, rate: int, channels: int, width: int) -> bytes:
    """받은 WAV 를 대본이 정한 규격(16kHz·mono·s16)의 헤더 없는 PCM 으로 맞춘다."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        src_ch, src_width, src_rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        pcm = w.readframes(w.getnframes())
    if src_width != width:
        pcm = audioop.lin2lin(pcm, src_width, width)
    if src_ch != channels:
        if channels != 1:
            raise SystemExit(f"모노 말고는 못 맞춥니다: {src_ch} → {channels}")
        pcm = audioop.tomono(pcm, width, 0.5, 0.5)
    if src_rate != rate:
        # ratecv 는 내림 필터를 함께 걸어 준다. 단순 솎아내기로 하면 앨리어싱이 생겨
        # STT 정확도가 떨어진다
        pcm, _ = audioop.ratecv(pcm, width, channels, src_rate, rate, None)
    return pcm


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


def _alerts(line: dict) -> bool:
    """이 줄이 화면에 경보 카드나 조력 카드를 띄우는가. `expect` 의 `alert <type>`·`assist <type>`.
    서버(`services/presets.py`)가 읽는 형식과 같다. `alert 없음` 은 제외."""
    for e in line.get("expect", []):
        tok = e.split()
        if len(tok) >= 2 and tok[0] in ("alert", "assist") and tok[1] != "없음":
            return True
    return False


def _jitter(line_id: str, span: int) -> int:
    """줄 id 로 정한 -span..+span 밀리초. 난수가 아니라서 몇 번을 돌려도 같다."""
    if span <= 0:
        return 0
    h = int.from_bytes(hashlib.sha256(line_id.encode()).digest()[:4], "big")
    return h % (2 * span + 1) - span


def gap_for(prev: dict, line: dict, cfg: dict) -> int:
    """앞 줄과 이 줄 사이에 둘 무음(밀리초). 위 모듈 주석의 표가 이 함수다."""
    same_speaker = prev["speaker"] == line["speaker"]
    if same_speaker:
        base = cfg.get("same_speaker_gap_ms", 700)
    elif _alerts(prev):
        base = cfg.get("alert_gap_ms", 2200)
    else:
        text = prev["text"]
        if text.rstrip().endswith("?") and len(text) <= cfg.get("question_max_chars", 45):
            base = cfg.get("question_gap_ms", 1050)
        elif len(text) >= cfg.get("long_text_chars", 55):
            base = cfg.get("long_gap_ms", 1750)
        else:
            base = cfg.get("gap_ms", 1300)
    gap = base + _jitter(line["id"], cfg.get("jitter_ms", 0))
    # 지터가 하한을 뚫지 못하게 클램프한다. 두 하한은 성격이 다르다
    if same_speaker:
        # `openai_file.py` 의 `SEGMENT_GAP_MS`(600ms) 보다 짧으면 그 경로에서 발화가 닫히지
        # 않고 다음 구간과 붙는다. 같은 사람이라 화자가 섞이지는 않지만, 두 문장이 한
        # 발화로 합쳐지면 줄 단위로 걸어 둔 기대 판정과 어긋난다
        gap = max(gap, cfg.get("same_speaker_min_gap_ms", 650))
    else:
        # 화자가 바뀌는 자리의 하한. 깨면 화자 분리가 두 사람을 섞는다
        gap = max(gap, cfg["min_gap_ms"])
    return gap


def build(preset_dir: Path, *, api_key: str | None, force: bool, write_start: bool) -> None:
    script = json.loads((preset_dir / "script.json").read_text(encoding="utf-8"))
    audio = script["audio"]
    rate, channels, width = audio["sample_rate"], audio["channels"], audio["sample_width_bytes"]
    bytes_per_ms = rate * channels * width // 1000
    model = audio.get("tts_model", "ssfm-v30")
    lines = script["lines"]
    clips_dir = preset_dir / "clips"
    clips_dir.mkdir(exist_ok=True)

    # 1) 클립
    client = httpx.Client(headers={"X-API-KEY": api_key}, timeout=180) if api_key else None
    for i, line in enumerate(lines):
        clip = clips_dir / f"{line['id']}.wav"
        if clip.exists() and not force:
            continue
        if client is None:
            raise SystemExit(f"클립이 없는데 --assemble-only 입니다: {clip}")
        tts = script["speakers"][line["speaker"]]["tts"]
        text = line_text(line)
        prev = line_text(lines[i - 1]) if i else ""
        nxt = line_text(lines[i + 1]) if i + 1 < len(lines) else ""
        pcm = to_pcm(synthesize(client, model, tts, text, prev, nxt), rate, channels, width)
        write_wav(clip, pcm, rate, channels, width)
        secs = len(pcm) // bytes_per_ms / 1000
        print(f"  {line['id']} {line['speaker']:8s} {secs:5.1f}s  {text[:30]}")

    # 2) 조립: 앞 클립 끝에 `gap_for` 만큼 쉬고 이어 붙인다. 첫 줄만 `start_ms`
    out = io.BytesIO()
    cursor_ms = 0
    timeline: list[tuple[str, int, int]] = []
    for i, line in enumerate(lines):
        pcm = read_pcm(clips_dir / f"{line['id']}.wav", rate, channels, width)
        want = lines[0]["start_ms"] if i == 0 else cursor_ms + gap_for(lines[i - 1], line, audio)
        out.write(b"\x00" * ((want - cursor_ms) * bytes_per_ms))
        out.write(pcm)
        dur = len(pcm) // bytes_per_ms
        cursor_ms = want + dur
        timeline.append((line["id"], want, dur))
    tail = audio.get("gap_ms", 1300)
    cursor_ms += tail
    out.write(b"\x00" * (tail * bytes_per_ms))

    target = preset_dir / audio["output"]
    write_wav(target, out.getvalue(), rate, channels, width)
    print(f"→ {target.relative_to(ROOT)}  {cursor_ms / 1000:.1f}s")
    prev_end = 0
    for idx, (lid, start, dur) in enumerate(timeline):
        rest = "" if idx == 0 else f"  쉼 {(start - prev_end) / 1000:.2f}s"
        print(f"    {lid} {start / 1000:6.1f}s +{dur / 1000:4.1f}s{rest}")
        prev_end = start + dur

    if write_start:
        _write_start(preset_dir / "script.json", timeline, cursor_ms)


def _write_start(path: Path, timeline: list[tuple[str, int, int]], total_ms: int) -> None:
    """포맷을 건드리지 않고 각 줄의 start_ms 와 duration_ms 만 바꿔 쓴다.

    대본이 두 포맷으로 쓰여 있다. dep-a·loan-b 는 `"id": "A01", "start_ms": 3000` 처럼 한 줄이고
    dep-d·loan-c 는 줄바꿈으로 갈라 놓았다. 그래서 사이 공백을 `\\s*` 로 받는다. 이전 판은
    한 줄만 잡아 뒤의 두 대본에서 죽었다(그 둘은 음원이 없어 드러나지 않았다).
    """
    text = path.read_text(encoding="utf-8")
    for lid, start, _ in timeline:
        text, n = re.subn(rf'("id": "{lid}",\s*"start_ms": )\d+', rf"\g<1>{start}", text, count=1)
        if n != 1:
            raise SystemExit(f"{path.name}: {lid} 의 start_ms 를 못 찾았습니다")
    text = re.sub(r'("duration_ms": )\d+', rf"\g<1>{total_ms}", text, count=1)
    path.write_text(text, encoding="utf-8")
    print(f"  start_ms·duration_ms 되씀 → {path.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="시연 대본 → Typecast TTS → audio.wav")
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
