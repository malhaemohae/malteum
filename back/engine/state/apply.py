"""판정·발화를 상태에 반영한다. 새 객체를 돌려주고 멱등이다.

apply    ver 는 (state, decided_by) 가 실제로 바뀔 때만 오른다. 같은 result 를 두 번 적용해도
         같은 상태.
observe  발화를 recent_utterances 창에 넣고 ⑧ 용어 밀도를 다시 잰다. fold 가 utterance
         이벤트에 하는 것과 같은 일이라 실시간 상태와 접은 상태가 같아진다.
"""

from __future__ import annotations

from dataclasses import replace

from contracts.engine_contract import ItemState, JudgeResult, Utterance, VerdictPayload
from engine.pack.compiler import CompiledPack
from engine.state import term_density
from engine.state.fold import RECENT_UTTERANCES
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


def observe(state: SessionState, utterance: Utterance, compiled: CompiledPack) -> SessionState:
    if any(u.utterance_id == utterance.utterance_id for u in state.recent_utterances):
        return state
    recent = (*state.recent_utterances, utterance)[-RECENT_UTTERANCES:]
    return replace(
        state, recent_utterances=recent, term_density=term_density.level(recent, compiled)
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
