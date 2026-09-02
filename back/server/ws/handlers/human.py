"""사람 결정 3종. STT 없이 도는 3층 폴백이다 (기획 7.1 ⑪).

`mark_met`·`mark_waived` 는 verdict 를 `decided_by=human` 으로 발행하고, `acknowledge` 는
경보를 `acknowledged=true` 로 다시 발행한다. 셋 다 앞선 이벤트를 `supersedes` 로 지목하는
새 이벤트이며, 기존 기록을 고치지 않는다.

엔진을 부르지 않는다. 그래서 STT 가 죽어도, LLM 키가 떨어져도 이 경로는 돈다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from server.services.session.pipeline import Pipeline
from server.services.session.registry import Session

Publish = Callable[[dict[str, Any]], Awaitable[Any]]

# 되돌릴 앞선 판정이 없으면 여기로 돌아간다. 출발 상태와 같다
FALLBACK_STATE = "unmet"


def _known(session: Session, item_code: str) -> bool:
    return session.pack.item(item_code) is not None


async def mark_met(
    session: Session, pipeline: Pipeline, item_code: str, undo: bool, publish: Publish
) -> str | None:
    """사람이 항목을 고지됨으로 찍는다. `undo` 면 앞선 판정으로 되돌린다.

    되돌리기는 기록을 지우는 것이 아니라 앞선 상태를 값으로 갖는 새 판정을 낸다.
    누가 언제 되돌렸는지가 남아야 감사가 성립한다.
    """
    if not _known(session, item_code):
        return f"팩에 없는 항목입니다: {item_code}"
    state = (pipeline.previous_state(session, item_code) or FALLBACK_STATE) if undo else "met"
    await pipeline.human_verdict(session, item_code, state, publish)
    return None


async def mark_waived(
    session: Session, pipeline: Pipeline, item_code: str, reason: str, publish: Publish
) -> str | None:
    """이 상담에서는 해당 없음으로 접는다. 계약상 waived 는 human 만 낼 수 있다."""
    if not _known(session, item_code):
        return f"팩에 없는 항목입니다: {item_code}"
    await pipeline.human_verdict(session, item_code, "waived", publish, waive_reason=reason)
    return None


async def acknowledge(
    session: Session, pipeline: Pipeline, alert_ref: str, publish: Publish
) -> str | None:
    """경보를 확인 처리한다. 위험 신호는 경보 + 확인 기록까지가 MVP 범위다(기획 10.3)."""
    if not await pipeline.acknowledge(session, alert_ref, publish):
        return f"그 경보를 찾을 수 없습니다: {alert_ref}"
    return None
