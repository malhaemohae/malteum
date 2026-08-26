"""출발 상태. 필수 항목 전부 unmet, 금지 항목 전부 clean. reference 항목은 판정 대상이 아니다."""

from __future__ import annotations

from typing import Literal

from contracts.engine_contract import ItemState, Mode
from engine.types import RulePack, SessionState

# 아직 판정이 없는 항목의 ver. 첫 판정이 ver 1 이 된다.
INITIAL_VER = 0


def initial_state(
    session_id: str,
    pack: RulePack,
    mode: Mode,
    customer_type: Literal["general", "professional"] = "general",
) -> SessionState:
    items = []
    for it in pack.items:
        if it.type == "required":
            items.append(_initial_item(it.code, "omission", "unmet"))
        elif it.type == "forbidden":
            items.append(_initial_item(it.code, "commission", "clean"))
    return SessionState(
        session_id=session_id,
        pack_version=pack.pack_version,
        mode=mode,
        customer_type=customer_type,
        items=tuple(items),
    )


def _initial_item(code, axis, state) -> ItemState:
    # decided_by 는 계약상 필수인데 초기 상태에는 결정 주체가 없다. L1 로 두고 ver 0 으로 구분한다.
    # 계약 확인 항목(임한빈): 초기 ItemState.decided_by 의미.
    return ItemState(item_code=code, axis=axis, state=state, decided_by="L1", ver=INITIAL_VER)
