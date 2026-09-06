"""L3 결정 → payload. 모델이 어겨서는 안 되는 규칙을 여기서 기계적으로 거른다.

거르는 것: 항목 타입·화자와 맞지 않는 축·상태, 사람 판정 덮어쓰기, met → unmet 되돌림,
waived, risk 항목 verdict, 팩에 없는 항목, 빠진 요소 없는 partial. evidence 는 모델이 아니라
팩에서 붙인다 (P4).

누적: 모델은 이번 발화만 보고 요소를 판정한다. 현재 partial 인 항목이면 이전에 채운 요소는
다시 요구하지 않고 (L1 required_verdict 의 known 과 같은 규칙) 남은 요소가 없으면 met 이 된다.
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
_ALLOWED = {
    ("required", "teller"): {("omission", "partial"), ("omission", "met")},
    ("required", "customer"): {("comprehension", "confirmed")},
    ("forbidden", "teller"): {("commission", "clean"), ("commission", "violated")},
}


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
        if (v.axis, v.state) not in _ALLOWED.get((item.type, utterance.speaker), set()):
            rejected.append(
                f"{v.item_code}: {item.type}/{utterance.speaker}에 {v.axis}/{v.state} 판정 불가"
            )
            continue
        cur = state.state_of(v.item_code, v.axis)
        if cur is not None and cur.decided_by == "human":
            rejected.append(f"{v.item_code}: 사람 판정은 L3가 변경할 수 없음")
            continue
        if (
            v.axis == "omission"
            and cur is not None
            and _ORDER.get(v.state, 0) < _ORDER.get(cur.state, 0)
        ):
            rejected.append(f"{v.item_code}: {cur.state} → {v.state} 되돌림 금지")
            continue
        if v.axis == "omission" and v.state == "partial":
            if not v.missing_elements:
                rejected.append(f"{v.item_code}: partial 인데 빠진 요소가 없음")
                continue
            if cur is not None and cur.state == "partial" and cur.missing_elements:
                still = tuple(
                    e
                    for e in item.requirement_elements
                    if e in cur.missing_elements and e in v.missing_elements
                )
                v = replace(v, state="met" if not still else "partial", missing_elements=still)
        if (
            cur is not None
            and cur.decided_by == "L3"
            and (cur.state, tuple(cur.missing_elements)) == (v.state, tuple(v.missing_elements))
        ):
            continue
        fixed = replace(
            v,
            decided_by="L3",
            utterance_ref=v.utterance_ref or ref,
            evidence=item.evidence,
            supersedes=None,
            # 누락 요소는 omission 에만 뜻이 있다. 모델이 violated 에 사유를 적어 보내는 일이 잦다
            missing_elements=v.missing_elements if v.axis == "omission" else (),
        )
        verdicts.append(fixed)
        if fixed.axis == "omission" and fixed.state == "partial":
            assists.append(nudge(item, fixed.missing_elements, ref))
    alerts = [replace(a, utterance_ref=a.utterance_ref or ref) for a in decision.alerts]
    return verdicts, alerts, assists, rejected
