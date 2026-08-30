"""trace 재생. 저장 이벤트를 타임스탬프대로 다시 화면에 흘린다.

계약이 정한 것 셋을 그대로 따른다.
  - 재생의 입력은 원본 세션의 이벤트다 (api.openapi.yaml `/sessions/{id}/events`)
  - 순서 기준은 `seq_in_session` 이다 (events.schema.json)
  - hello 를 받은 서버가 ready 직후 스스로 시작한다. 별도 시작 메시지는 없다
    (ws_protocol.schema.json)

**STT·LLM 을 부르지 않는다.** 판정은 이미 이벤트에 들어 있고 여기서는 다시 판정하지
않는다. 그래서 STT 가 죽어도, LLM 키가 떨어져도 이 경로는 돈다(기획 11.4·리스크 1·6).

**재생 이벤트를 다시 저장하지 않는다.** 이벤트가 정본인데 재생할 때마다 사본이 쌓이면
리포트와 감사가 같은 상담을 여러 번 세게 된다. trace 세션은 자기 봉투
(session_started·session_ended)만 남기고, 화면에 나가는 내용은 원본에서 읽는다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from contracts.engine_contract import Engine, RulePack
from server.mapping import event_to_s2c
from server.services.session import chains

Publish = Callable[[dict[str, Any]], Awaitable[Any]]


def _gap_seconds(previous: dict[str, Any], current: dict[str, Any]) -> float:
    """원본의 간격을 그대로 쓴다.

    계약이 "타임스탬프대로 재생" 을 요구하고, 재현성 증명은 화면이 원본과 같은 속도로
    흐를 때만 성립한다. 상한을 두면 긴 침묵이 짧아져 재생이 원본과 달라진다.
    시나리오 A 만 해도 5 초를 넘는 간격이 13 개, 최대 34.9 초다.
    음수만 막는다(시계 역전 방어).
    """
    delta = (
        datetime.fromisoformat(current["occurred_at"])
        - datetime.fromisoformat(previous["occurred_at"])
    ).total_seconds()
    return max(delta, 0.0)


async def replay(
    engine: Engine,
    pack: RulePack,
    events: list[dict[str, Any]],
    publish: Publish,
) -> None:
    """원본 이벤트를 순서대로 s2c 로 바꿔 보낸다. 상태는 매 시점까지 접어 만든다."""
    ordered = chains.by_seq(events)
    assist_vers = chains.assist_versions(ordered)
    previous: dict[str, Any] | None = None
    for i, event in enumerate(ordered):
        if previous is not None:
            await asyncio.sleep(_gap_seconds(previous, event))
        previous = event
        # 그 시점까지의 상태. 실시간 경로와 같은 fold 를 써야 두 값이 갈라지지 않는다
        state = engine.fold(ordered[: i + 1])
        message = event_to_s2c.from_event(event, state, assist_vers.get(event["event_id"], 1))
        if message is not None:
            await publish(message)
        if event["kind"] == "verdict":
            await publish(event_to_s2c.progress(pack, state))
