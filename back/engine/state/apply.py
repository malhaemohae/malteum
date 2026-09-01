"""판정을 상태에 반영한다. 새 객체를 돌려주고 멱등이다.

ver 는 (state, decided_by) 가 실제로 바뀔 때만 오른다. 같은 result 를 두 번 적용해도 같은 상태.
"""

from __future__ import annotations

from dataclasses import replace

from contracts.engine_contract import ItemState, JudgeResult, VerdictPayload
from engine.types import SessionState


def apply(state: SessionState, result: JudgeResult) -> SessionState:
    for v in result.verdicts:
        if v.state == "waived" and (not v.waive_reason or v.decided_by != "human"):
            raise ValueError("waive_reason 필수: waived 는 사람만, 사유와 함께")
    items = list(state.items)
    for v in result.verdicts:
        idx = next(
            (i for i, s in enumerate(items) if s.item_code == v.item_code and s.axis == v.axis),
            None,
        )
        if idx is None:
            items.append(_new_item(v, ver=1))
        else:
            cur = items[idx]
            if (cur.state, cur.decided_by) != (v.state, v.decided_by):
                items[idx] = replace(
                    cur,
                    state=v.state,
                    decided_by=v.decided_by,
                    ver=cur.ver + 1,
                    missing_elements=v.missing_elements,
                    waive_reason=v.waive_reason,
                )
    return replace(
        state,
        items=tuple(items),
        alert_count=state.alert_count + len(result.alerts) if result.alerts else state.alert_count,
    )


def _new_item(v: VerdictPayload, ver: int) -> ItemState:
    return ItemState(
        item_code=v.item_code,
        axis=v.axis,
        state=v.state,
        decided_by=v.decided_by,
        ver=ver,
        missing_elements=v.missing_elements,
        waive_reason=v.waive_reason,
    )
