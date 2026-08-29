"""L3 결정 → payload. 모델이 어겨서는 안 되는 규칙을 여기서 기계적으로 거른다.

거르는 것: met → unmet 되돌림, waived, risk 항목 verdict, 고객 발화에 대한 commission verdict,
팩에 없는 항목. evidence 는 모델이 아니라 팩에서 붙인다 (P4).
"""

from __future__ import annotations

from dataclasses import replace

from contracts.engine_contract import (
    AlertPayload,
    AssistPayload,
    JudgeDecision,
    Utterance,
    VerdictPayload,
)
from engine.assist.nudge import nudge
from engine.types import RulePack, SessionState

_ORDER = {"unmet": 0, "partial": 1, "met": 2, "waived": 3}


def parse(
    decision: JudgeDecision, pack: RulePack, state: SessionState, utterance: Utterance
) -> tuple[list[VerdictPayload], list[AlertPayload], list[AssistPayload], list[str]]:
    verdicts: list[VerdictPayload] = []
    assists: list[AssistPayload] = list(decision.assists)
    rejected: list[str] = []
    ref = utterance.utterance_id
    for v in decision.verdicts:
        item = pack.item(v.item_code)
        if item is None or item.type == "risk" or item.type == "reference":
            rejected.append(f"{v.item_code}: 판정 대상 아님")
            continue
        if v.state == "waived":
            rejected.append(f"{v.item_code}: waived 는 사람만")
            continue
        if v.axis == "commission" and utterance.speaker != "teller":
            rejected.append(f"{v.item_code}: 고객 발화는 금지 발언이 아님")
            continue
        cur = state.state_of(v.item_code, v.axis)
        if (
            v.axis == "omission"
            and cur is not None
            and _ORDER.get(v.state, 0) < _ORDER.get(cur.state, 0)
        ):
            rejected.append(f"{v.item_code}: {cur.state} → {v.state} 되돌림 금지")
            continue
        if cur is not None and cur.state == v.state and cur.decided_by == "L3":
            continue
        fixed = replace(
            v,
            decided_by="L3",
            utterance_ref=v.utterance_ref or ref,
            evidence=item.evidence,
            supersedes=None,
        )
        verdicts.append(fixed)
        if fixed.axis == "omission" and fixed.state == "partial":
            assists.append(nudge(item, fixed.missing_elements, ref))
    alerts = [replace(a, utterance_ref=a.utterance_ref or ref) for a in decision.alerts]
    return verdicts, alerts, assists, rejected
