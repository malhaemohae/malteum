"""종료 요약(session_ended.summary). 상태의 파생물이며 validate.py 의 접기 규칙과 같다."""

from __future__ import annotations

from collections.abc import Sequence

from engine.types import RulePack, SessionState


def summarize(state: SessionState, pack: RulePack, events: Sequence[dict] = ()) -> dict:
    counted = {"met": 0, "partial": 0, "unmet": 0, "waived": 0}
    final = {(s.item_code, s.axis): s.state for s in state.items}
    for it in pack.required_items():
        counted[final.get((it.code, "omission"), "unmet")] += 1
    violations = sum(1 for (_, ax), s in final.items() if ax == "commission" and s == "violated")
    superseded = {e["supersedes"] for e in events if e.get("supersedes")}
    adopted = sum(
        1
        for e in events
        if e["kind"] == "assist"
        and e["event_id"] not in superseded
        and e["assist"].get("outcome") == "adopted"
    )
    return {
        "items_total": len(pack.required_items()),
        **counted,
        "violations": violations,
        "alerts": state.alert_count,
        "assists_adopted": adopted,
    }
