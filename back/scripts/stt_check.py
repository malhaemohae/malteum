#!/usr/bin/env python3
"""Deepgram 실호출 검증. 기획 19장 「STT 공급자」 결정의 닫히는 조건.

**재는 것은 연결 여부가 아니라 도메인 용어와 숫자 표기의 적중률이다**(검증결과.md 3절).
`중도해지이율`·`금리인하요구권` 같은 말이 깨지면 L1 이 그 항목을 아예 못 잡고,
`0.5 퍼센트` 가 `0.5%` 로 안 오면 ⑤ 숫자 오류 감지가 대조할 값을 잃는다.

기획 11.3 이 정한 조합을 그대로 켠다 — nova-3 · `ko` · keyterm · numerals ·
`mip_opt_out`(13장이 라이선스 조건으로 정한 학습 사용 거부).

스트리밍으로 보내는 이유
    계약 s2c `partial` 이 200~400ms 중간 전사를 요구한다. 파일을 통째로 올리는 배치
    전사로는 그 동작을 확인할 수 없어, 실제 쓸 경로인 WebSocket 으로 잰다.

사용
    uv run python scripts/stt_check.py --make-audio        # 음원부터 만든다 (Windows)
    uv run python scripts/stt_check.py                     # scripts/stt_audio/*.wav 전부
    uv run python scripts/stt_check.py path/to.wav
    uv run python scripts/stt_check.py --no-keyterm        # keyterm 없이 대조
    APP_STT_API_KEY 를 .env 에서 읽는다.

음원 주의
    Windows 내장 한국어 음성(Heami)으로 만든다. 계정도 비용도 필요 없어 1차 검증에는
    쓸 수 있지만 **구형 합성음이라 실제 상담 음성보다 쉽다.** 최종 판단은 사람 목소리나
    시연용 TTS 로 해야 한다(검증결과.md 3절).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import wave
from pathlib import Path

BACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACK))

sys.stdout.reconfigure(encoding="utf-8")

from server.bootstrap.settings import get_settings  # noqa: E402

AUDIO_DIR = BACK / "scripts" / "stt_audio"
FRAME_MS = 100  # 계약 audioFrame 과 같은 크기로 보낸다

# 팩의 jargon_terms 에서 온 것. keyterm 으로 주입하고, 전사에 살아남는지 본다
KEYTERMS = [
    "중도해지이율",
    "우대이자율",
    "만기후이자율",
    "차감률",
    "예금자보호법",
    "금리인하요구권",
    "총부채원리금상환비율",
    "중도상환해약금",
]

# 파일별로 "이 말과 이 숫자가 나와야 한다"
EXPECT: dict[str, dict[str, list[str]]] = {
    "deposit_1": {"terms": ["해지"], "numbers": []},
    "deposit_2": {"terms": ["중도해지"], "numbers": ["0.5"]},
    "deposit_3": {"terms": ["우대이자율", "중도해지", "만기후이자율"], "numbers": []},
    "loan_1": {"terms": ["금리인하요구권", "총부채원리금상환비율"], "numbers": []},
}


# 시나리오 A(정기예금 중도해지)와 주담대 용어에서 뽑은 발화. 파일명이 EXPECT 의 키다
SCRIPT_LINES = {
    "deposit_1": "지금 해지하면 얼마나 받을 수 있어요?",
    "deposit_2": "중도해지하시면 0.5 퍼센트 정도는 받으세요.",
    "deposit_3": "우대이자율은 중도해지하시면 적용이 안 되고요, 만기후이자율도 따로 있습니다.",
    "loan_1": "금리인하요구권과 총부채원리금상환비율을 안내드리겠습니다.",
}


def make_audio() -> None:
    """Windows 내장 한국어 음성으로 테스트 음원을 만든다. 16kHz mono PCM16 —
    계약 `audioFrame` 과 같은 규격이라 그대로 흘려보낼 수 있다."""
    import subprocess

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(
        f"$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('Microsoft Heami Desktop');"
        f"$s.SetOutputToWaveFile('{AUDIO_DIR / (name + '.wav')}',$f);"
        f"$s.Speak('{text}');$s.Dispose()"
        for name, text in SCRIPT_LINES.items()
    )
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
        "16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        "[System.Speech.AudioFormat.AudioChannel]::Mono);" + lines
    )
    r = subprocess.run(  # noqa: S603
        ["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True
    )
    if r.returncode != 0:
        raise SystemExit(f"음원 생성 실패(Windows 전용): {r.stderr[:200]}")
    for p in sorted(AUDIO_DIR.glob("*.wav")):
        print(f"  {p.name}  {p.stat().st_size:,} bytes")


def read_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit(f"16bit mono 가 아닙니다: {path.name}")
        return w.readframes(w.getnframes()), w.getframerate()


def url(settings, keyterm: bool, rate: int) -> str:
    q = [
        f"model={settings.stt_model}",
        f"language={settings.stt_language}",
        "encoding=linear16",
        "channels=1",
        # raw linear16 은 표본율을 헤더로 못 알려준다. 안 주면 Deepgram 이 제 값으로
        # 해석해 소리가 어긋나고 전사가 빈 채로 돌아온다
        f"sample_rate={rate}",
        "numerals=true",  # 구어 수치 → 숫자. ⑤ 숫자 오류 감지의 전제
        "punctuate=true",
        "interim_results=true",  # partial 이 실제로 오는지 본다
    ]
    if settings.stt_mip_opt_out:
        q.append("mip_opt_out=true")  # 13장: 할인을 포기하고 학습 사용 거부
    if keyterm:
        q += [f"keyterm={t}" for t in KEYTERMS]
    return "wss://api.deepgram.com/v1/listen?" + "&".join(q)


async def transcribe(path: Path, settings, keyterm: bool) -> tuple[str, int, float]:
    import websockets

    pcm, rate = read_pcm(path)
    chunk = rate * 2 * FRAME_MS // 1000
    finals: list[str] = []
    partials = 0
    first_partial_ms = -1.0

    async with websockets.connect(
        url(settings, keyterm, rate),
        additional_headers={"Authorization": f"Token {settings.stt_api_key}"},
        open_timeout=30,
    ) as ws:
        loop = asyncio.get_running_loop()
        t0 = loop.time()

        async def send() -> None:
            for i in range(0, len(pcm), chunk):
                await ws.send(pcm[i : i + chunk])
                await asyncio.sleep(FRAME_MS / 1000)  # 실시간 속도로 흘린다
            await ws.send(json.dumps({"type": "CloseStream"}))

        async def recv() -> None:
            nonlocal partials, first_partial_ms
            while True:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
                except (TimeoutError, websockets.exceptions.ConnectionClosed):
                    return  # 서버가 스트림을 닫으면 거기까지가 결과다
                if msg.get("type") != "Results":
                    continue
                text = msg["channel"]["alternatives"][0]["transcript"]
                if not text:
                    continue
                if msg.get("is_final"):
                    finals.append(text)
                else:
                    partials += 1
                    if first_partial_ms < 0:
                        first_partial_ms = (loop.time() - t0) * 1000

        await asyncio.gather(send(), recv())
    return " ".join(finals), partials, first_partial_ms


def score(name: str, text: str) -> tuple[int, int, list[str]]:
    want = EXPECT.get(name, {"terms": [], "numbers": []})
    flat = re.sub(r"\s+", "", text)
    missed = []
    hit = 0
    for t in want["terms"]:
        if re.sub(r"\s+", "", t) in flat:
            hit += 1
        else:
            missed.append(t)
    for n in want["numbers"]:
        if n in text:
            hit += 1
        else:
            missed.append(f"숫자 {n}")
    return hit, len(want["terms"]) + len(want["numbers"]), missed


async def main() -> int:
    ap = argparse.ArgumentParser(description="Deepgram 한국어 실호출 검증")
    ap.add_argument("audio", nargs="*", help="wav 경로. 없으면 scripts/stt_audio/*.wav")
    ap.add_argument("--no-keyterm", action="store_true", help="keyterm 주입 없이 대조")
    ap.add_argument("--make-audio", action="store_true", help="테스트 음원 생성 (Windows)")
    args = ap.parse_args()

    if args.make_audio:
        make_audio()
        print()

    settings = get_settings()
    if not settings.stt_api_key:
        raise SystemExit("APP_STT_API_KEY 가 없습니다. .env 를 확인하세요.")

    paths = [Path(a) for a in args.audio] or sorted(AUDIO_DIR.glob("*.wav"))
    if not paths:
        raise SystemExit(f"음원이 없습니다: {AUDIO_DIR}")

    keyterm = not args.no_keyterm
    on = "켬" if keyterm else "끔"
    print(f"모델 {settings.stt_model} · 언어 {settings.stt_language} · keyterm {on}")
    print(f"mip_opt_out {settings.stt_mip_opt_out} (13장 학습 사용 거부)\n")

    total_hit = total_want = 0
    for p in paths:
        try:
            text, partials, first_ms = await transcribe(p, settings, keyterm)
        except Exception as e:  # noqa: BLE001  무엇이 막았는지 그대로 보여준다
            print(f"[ 실패 ] {p.name}  {type(e).__name__}: {e}")
            return 1
        hit, want, missed = score(p.stem, text)
        total_hit += hit
        total_want += want
        mark = "  OK  " if hit == want else " MISS "
        print(f"[{mark}] {p.name}   적중 {hit}/{want}")
        print(f"         전사: {text}")
        print(f"         partial {partials}건 · 첫 partial {first_ms:.0f}ms")
        if missed:
            print(f"         놓침: {', '.join(missed)}")
        print()

    print("=" * 54)
    print(f"도메인 용어·숫자 적중 {total_hit}/{total_want}")
    return 0 if total_hit == total_want else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
