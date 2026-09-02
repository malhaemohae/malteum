"""Deepgram 스트리밍 어댑터.

파라미터는 `scripts/stt_check.py` 로 실측한 조합 그대로다(2026-09-02, 적중 8/8).
바꾸려면 그 스크립트를 다시 돌려 근거를 남긴다.

    nova-3 · ko          기획 11.3
    numerals=true        구어 수치 → 숫자. ⑤ 숫자 오류 감지의 전제
    keyterm              팩의 jargon_terms. 끄면 `만기후이자율` 이 `만기 후 이자율` 로
                         갈라져 L1 정확 일치가 깨진다 (실측)
    mip_opt_out=true     13장이 라이선스 조건으로 정한 학습 사용 거부
    sample_rate          raw linear16 은 표본율을 헤더로 못 알린다. 빼면 전사가 빈다
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from contextlib import suppress
from urllib.parse import quote

from server.services.stt.base import OnTranscript, Transcript

ENDPOINT = "wss://api.deepgram.com/v1/listen"
SAMPLE_RATE = 16_000


class DeepgramAdapter:
    def __init__(
        self,
        api_key: str,
        model: str = "nova-3",
        language: str = "ko",
        *,
        mip_opt_out: bool = True,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.language = language
        self.mip_opt_out = mip_opt_out

    def _url(self, keyterms: Sequence[str]) -> str:
        q = [
            f"model={self.model}",
            f"language={self.language}",
            "encoding=linear16",
            "channels=1",
            f"sample_rate={SAMPLE_RATE}",
            "numerals=true",
            "punctuate=true",
            "interim_results=true",
        ]
        if self.mip_opt_out:
            q.append("mip_opt_out=true")
        q += [f"keyterm={quote(t)}" for t in keyterms]
        return f"{ENDPOINT}?" + "&".join(q)

    async def open(
        self, on_transcript: OnTranscript, keyterms: Sequence[str] = ()
    ) -> DeepgramStream:
        import websockets

        ws = await websockets.connect(
            self._url(keyterms),
            additional_headers={"Authorization": f"Token {self.api_key}"},
            open_timeout=15,
        )
        return DeepgramStream(ws, on_transcript)


class DeepgramStream:
    """상담 하나에 소켓 하나. 받는 쪽은 배경 태스크로 돈다."""

    def __init__(self, ws, on_transcript: OnTranscript) -> None:
        self.ws = ws
        self.on_transcript = on_transcript
        self.reader = asyncio.create_task(self._read())

    async def send(self, pcm: bytes) -> None:
        await self.ws.send(pcm)

    async def _read(self) -> None:
        import websockets

        try:
            while True:
                msg = json.loads(await self.ws.recv())
                if msg.get("type") != "Results":
                    continue
                alt = msg["channel"]["alternatives"][0]
                text = alt.get("transcript", "")
                if not text:
                    continue
                await self.on_transcript(
                    Transcript(
                        text=text,
                        final=bool(msg.get("is_final")),
                        confidence=alt.get("confidence"),
                        start_ms=int(msg["start"] * 1000) if "start" in msg else None,
                        duration_ms=int(msg["duration"] * 1000) if "duration" in msg else None,
                    )
                )
        except (asyncio.CancelledError, websockets.exceptions.ConnectionClosed):
            raise
        except Exception:  # noqa: BLE001  전사 하나가 상담을 끊지 않게 한다
            return

    async def aclose(self) -> None:
        # CloseStream 을 보내면 Deepgram 이 남은 전사를 마저 준다. 그냥 끊으면 마지막
        # 발화가 사라지고, 그 발화가 리포트의 마지막 항목일 수 있다
        with suppress(Exception):
            await self.ws.send(json.dumps({"type": "CloseStream"}))
            await asyncio.wait_for(asyncio.shield(self.reader), timeout=3)
        self.reader.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await self.reader
        with suppress(Exception):
            await self.ws.close()
