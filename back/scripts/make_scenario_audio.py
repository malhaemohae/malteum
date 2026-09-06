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

    앞 줄이 경보·카드를 냄  `alert_gap_ms`(2.2초). 심사위원이 카드를 읽을 시간. 다음에 말하는
                            사람이 누구인지와 무관하므로 화자 판정보다 **먼저** 본다
    같은 화자가 이어 말함   `same_speaker_gap_ms`(0.78초). 한 사람이 문장을 잇는 자리라
                            화자 분리가 가를 필요가 없다
    앞 줄이 긴 설명         `long_gap_ms`(1.75초). `long_text_chars`(55자) 이상. 소화할 틈
    그 밖                   `gap_ms`(1.3초)

길이는 `text` 가 아니라 실제로 소리 나는 문장(`tts_text` 가 있으면 그것)으로 잰다.

"짧은 물음은 빨리 받는다" 는 분기도 있었으나 뺐다. 네 대본의 물음표로 끝나는 줄 여섯 개 중
넷은 되물음이라 재진술 카드를 함께 내어 위의 경보 판정이 먼저 잡고, 나머지 둘은 49자·63자로
짧지도 않다. 어느 순서로 놓든 한 번도 타지 않는 분기였다.

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
# 클립을 만든 설정의 지문 장부. `clips/` 안에 두므로 커밋되지 않는다
STAMP_FILE = "fingerprints.json"

# `script.json` 의 `audio` 가 이 값들을 덮어쓴다. 한자리에 모아 두는 이유는 옛 판에서 같은
# 숫자를 코드 기본값과 네 대본에 나눠 적었다가 실제로 어긋났기 때문이다(`jitter_ms` 가
# 코드에서는 0, 대본에서는 120). 지금 네 대본은 이 키를 모두 갖고 있어 기본값이 쓰이지
# 않지만, 다섯 번째 대본을 줄여 쓰더라도 여기 값으로 채워진다
GAP_DEFAULTS = {
    "gap_ms": 1300,
    "long_gap_ms": 1750,
    "same_speaker_gap_ms": 780,
    "alert_gap_ms": 2200,
    "jitter_ms": 120,
    "long_text_chars": 55,
    "min_gap_ms": 1000,
    "same_speaker_min_gap_ms": 650,
}


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


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def request_body(model: str, tts: dict, text: str, prev: str, nxt: str) -> dict:
    """Typecast 에 보낼 요청 본문.

    `synthesize` 와 `_stamp` 가 **같은 함수**를 부른다. 옛 판은 두 곳이 각각
    `tts.get("volume", 100)` 같은 기본값을 따로 적어 두어, 한쪽만 고치면 지문이 실제로 보낸
    요청과 다른 것을 추적하기 시작했다. 그러면 캐시가 낡은 클립을 조용히 통과시킨다.
    지문 장부를 둔 이유가 바로 그 사고이므로 같은 모양을 두 번 만들지 않는다.

    `prompt` 의 smart 감정은 앞뒤 대사를 보고 억양을 정한다. 이 값이 혼잣말이 아니라 대화로
    들리게 하는 가장 큰 요인이다.
    """
    prompt: dict = {"emotion_type": "smart"}
    if prev:
        prompt["previous_text"] = prev
    if nxt:
        prompt["next_text"] = nxt
    return {
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
        "seed": int.from_bytes(_digest(text)[:4], "big"),
    }


def synthesize(client: httpx.Client, body: dict) -> bytes:
    """Typecast 가 준 WAV 바이트를 그대로 돌려준다."""
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


def _stamp(body: dict) -> str:
    """이 클립을 만든 요청의 지문. 요청이 한 글자라도 다르면 캐시를 버려야 한다.

    `request_body` 가 만든 그 본문을 그대로 해시하므로, 보낸 것과 기록한 것이 구조적으로
    어긋날 수 없다. 앞뒤 문맥(`prompt`)까지 들어가서 이웃 줄을 고쳐 억양이 달라지는 경우도
    잡힌다. `seed` 는 `text` 에서 나온 값이라 따로 셀 필요가 없지만 빼지 않는다. 본문을
    그대로 해시하는 편이 규칙이 하나라 안전하다.
    """
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _read_stamps(path: Path) -> dict[str, str]:
    """지문 장부. 없으면 빈 것을 돌려주고, 그러면 클립이 있어도 전부 다시 만든다.

    `clips/` 는 커밋하지 않으므로(SCRIPT.md 4.3) 남의 기계에 있는 클립이 어느 공급자·보이스로
    만들어진 것인지 알 길이 없다. 2026-09-06 에 ElevenLabs 에서 Typecast 로 옮길 때 이 장부가
    없어서, 옛 클립이 남은 기계에서 그대로 돌리면 옛 목소리와 새 간격이 섞인 음원이 나오면서도
    아무 경고가 안 났다. 파일이 있느냐만 보던 캐시를 설정 지문으로 바꾼 이유다.
    """
    if not path.exists():
        return {}
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return got if isinstance(got, dict) else {}


def _jitter(line_id: str, span: int) -> int:
    """줄 id 로 정한 -span..+span 밀리초. 난수가 아니라서 몇 번을 돌려도 같다."""
    if span <= 0:
        return 0
    return int.from_bytes(_digest(line_id)[:4], "big") % (2 * span + 1) - span


def gap_for(prev: dict, line: dict, cfg: dict) -> int:
    """앞 줄과 이 줄 사이에 둘 무음(밀리초). 위 모듈 주석의 표가 이 함수다.

    `cfg` 는 `settings` 가 채워 준 것이라 모든 키가 있다고 보고 직접 인덱싱한다.

    **경보·카드 판정이 화자보다 먼저다.** 카드를 읽을 시간은 다음에 말하는 사람이 누구인지와
    상관이 없다. 순서를 뒤집었던 판에서는 은행원이 카드를 낸 뒤 자기가 이어 말하는 자리
    네 곳(A03→A04 · D04→D05 · D15→D16 · C13→C14)이 0.74~0.88초로 지나가 심사위원이
    카드를 못 읽었다.

    길이 판정에는 `line_text` 를 쓴다. 실제로 소리 나는 문장이 그것이고, `tts_text` 는 숫자를
    풀어 적어(`15.4%` → `십오 점 사 퍼센트`) `text` 보다 길다.
    """
    same_speaker = prev["speaker"] == line["speaker"]
    if _alerts(prev):
        base = cfg["alert_gap_ms"]
    elif same_speaker:
        base = cfg["same_speaker_gap_ms"]
    elif len(line_text(prev)) >= cfg["long_text_chars"]:
        base = cfg["long_gap_ms"]
    else:
        base = cfg["gap_ms"]
    gap = base + _jitter(line["id"], cfg["jitter_ms"])
    # 지터가 하한을 뚫지 못하게 클램프한다. 근거는 모듈 주석의 "지터가 뚫지 못하는 두 하한".
    # 지금 값에서는 둘 다 안 걸리지만(같은 화자 780-120=660 > 650, 화자 전환 1300-120=1180
    # > 1000) 기준값을 내리거나 `jitter_ms` 를 올리면 이 클램프가 유일한 방어선이 된다
    floor = "same_speaker_min_gap_ms" if same_speaker else "min_gap_ms"
    return max(gap, cfg[floor])


def build(preset_dir: Path, *, client: httpx.Client | None, force: bool, write_start: bool) -> None:
    script = json.loads((preset_dir / "script.json").read_text(encoding="utf-8"))
    # 대본이 적은 값이 기본값을 덮는다. 이 뒤로는 키가 다 있다고 보고 직접 인덱싱한다
    audio = {**GAP_DEFAULTS, **script["audio"]}
    rate, channels, width = audio["sample_rate"], audio["channels"], audio["sample_width_bytes"]
    bytes_per_ms = rate * channels * width // 1000
    model = audio.get("tts_model", "ssfm-v30")
    lines = script["lines"]
    clips_dir = preset_dir / "clips"
    clips_dir.mkdir(exist_ok=True)

    # 1) 클립
    stamp_path = clips_dir / STAMP_FILE
    stamps = _read_stamps(stamp_path)
    for i, line in enumerate(lines):
        clip = clips_dir / f"{line['id']}.wav"
        text = line_text(line)
        body = request_body(
            model,
            script["speakers"][line["speaker"]]["tts"],
            text,
            line_text(lines[i - 1]) if i else "",
            line_text(lines[i + 1]) if i + 1 < len(lines) else "",
        )
        fingerprint = _stamp(body)
        if clip.exists() and stamps.get(line["id"]) == fingerprint and not force:
            continue
        if client is None:
            why = "클립이 없습니다" if not clip.exists() else "클립이 지금 설정과 다릅니다"
            raise SystemExit(f"{why}: {clip} (--assemble-only 라 새로 못 만듭니다)")
        pcm = to_pcm(synthesize(client, body), rate, channels, width)
        write_wav(clip, pcm, rate, channels, width)
        stamps[line["id"]] = fingerprint
        # 줄마다 적어 둔다. 한 회차가 유료 호출이라 중간에 죽어도 이미 쓴 돈이 안 날아간다.
        # 통째로 쓰다 죽으면 JSON 이 깨지므로 임시 파일에 쓰고 갈아 끼운다
        tmp = stamp_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(stamps, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, stamp_path)
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

    def run(client: httpx.Client | None) -> int:
        for d in presets:
            print(f"[{d.name}]")
            build(d, client=client, force=args.force, write_start=args.write_start)
        return 0

    if args.assemble_only:
        return run(None)
    # 프리셋마다 새로 만들지 않는다. 연결을 이어 써 TLS 악수를 한 번만 한다
    with httpx.Client(headers={"X-API-KEY": load_api_key()}, timeout=180) as client:
        return run(client)


if __name__ == "__main__":
    sys.exit(main())
