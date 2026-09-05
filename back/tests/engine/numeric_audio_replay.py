"""로컬 실험 서버의 replay 경로로 TTS 두 음원을 재생하고 이벤트·요약을 보존한다.

먼저 서버 STT를 로컬 Qwen ASR 주소로 명시해 실행한다. 출력 디렉터리는 실행마다 분리한다.
    NUMERIC_OUTPUT_DIR=/tmp/numeric-8b uv run python tests/engine/numeric_audio_replay.py
"""

import asyncio
import json
import os
import sys
import time
import wave
from collections import Counter
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[3]

OUT = Path(os.environ["NUMERIC_OUTPUT_DIR"])
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:18000"


async def run(preset):
    script = json.loads((ROOT / "assets/scenarios" / preset / "script.json").read_text())
    with wave.open(str(ROOT / "assets/scenarios" / preset / "audio.wav")) as wav:
        seconds = wav.getnframes() / wav.getframerate()
    async with httpx.AsyncClient(base_url=BASE, timeout=180) as client:
        response = await client.post(
            "/api/sessions",
            json={
                "mode": "replay",
                "pack_version": script["pack_version"],
                "audio_ref": f"scenarios/{preset}/audio.wav",
                "customer_profile": {"type": "general"},
            },
        )
        response.raise_for_status()
        sid = response.json()["session_id"]
        messages = []
        print(
            json.dumps({"preset": preset, "session_id": sid, "audio_seconds": seconds}), flush=True
        )
        started = time.monotonic()
        async with websockets.connect(
            BASE.replace("http:", "ws:") + "/ws", ping_timeout=120
        ) as sock:
            await sock.send(json.dumps({"t": "hello", "mode": "replay", "session_id": sid}))
            last_event = started
            while True:
                elapsed = time.monotonic() - started
                if elapsed > seconds + 30 and time.monotonic() - last_event > 8:
                    break
                if elapsed > seconds + 90:
                    raise TimeoutError("replay did not settle")
                try:
                    msg = json.loads(await asyncio.wait_for(sock.recv(), 1))
                except TimeoutError:
                    continue
                if msg["t"] == "ping":
                    await sock.send(json.dumps({"t": "pong"}))
                    continue
                messages.append(msg)
                last_event = time.monotonic()
                if msg["t"] in ("utterance", "alert", "error"):
                    print(
                        json.dumps(
                            {"preset": preset, "elapsed": round(elapsed, 1), **msg},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            await sock.send(json.dumps({"t": "end"}))
            while True:
                msg = json.loads(await asyncio.wait_for(sock.recv(), 30))
                messages.append(msg)
                if msg["t"] == "ended":
                    break
        await asyncio.sleep(3)
        events_response = await client.get(f"/api/sessions/{sid}/events")
        events_response.raise_for_status()
        events = events_response.json()["events"]
        report_response = await client.get(f"/api/sessions/{sid}/report")
        report_response.raise_for_status()
        report = report_response.json()
        numeric = [
            e
            for e in events
            if e["kind"] == "alert" and e["alert"]["alert_type"] == "number_mismatch"
        ]
        end_seq = next(e["seq_in_session"] for e in events if e["kind"] == "session_ended")
        result = {
            "preset": preset,
            "session_id": sid,
            "audio_seconds": seconds,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "expected_summary": script.get("expected_summary"),
            "messages": messages,
            "events": events,
            "report": report,
        }
        (OUT / f"{preset}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    "preset": preset,
                    "kinds": dict(Counter(e["kind"] for e in events)),
                    "numeric_alerts": [e["alert"] for e in numeric],
                    "summary": next(
                        e["session_ended"]["summary"]
                        for e in events
                        if e["kind"] == "session_ended"
                    ),
                    "events_after_end": sum(e["seq_in_session"] > end_seq for e in events),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


async def main():
    for preset in sys.argv[1:] or ["preset-dep-a", "preset-loan-b"]:
        await run(preset)


if __name__ == "__main__":
    asyncio.run(main())
