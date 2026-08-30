"""증빙 리포트. 화면 렌더용 JSON 이고 PDF 와 같은 내용이다(계약).

이벤트를 접어 만든다. 투영이나 메모리를 보지 않으므로 세션이 끝난 뒤에도, 서버가
재시작된 뒤에도 같은 값이 나온다. 요약은 engine.summarize 를 그대로 쓴다 — 실시간
화면과 리포트가 다른 수를 말하면 안 된다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contracts.engine_contract import Engine, RulePack

# 계약이 리포트에 항상 넣으라고 한 문구. 판정의 성질을 산출물이 스스로 밝힌다
DISCLAIMER = (
    "이해 축(comprehension)은 고객의 이해를 돕기 위한 참고 정보이며 판정의 근거가 아닙니다. "
    "필수 고지 이행 여부는 누락 축(omission), 금지 발언은 위반 축(commission) 판정으로 봅니다."
)


def _t_ms(event: dict[str, Any], started: datetime) -> int:
    delta = datetime.fromisoformat(event["occurred_at"]) - started
    return max(int(delta.total_seconds() * 1000), 0)


def _label(event: dict[str, Any], names: dict[str, str]) -> str:
    kind, body = event["kind"], event[event["kind"]]
    if kind == "utterance":
        return f"{body['speaker']}: {body['text']}"
    if kind == "verdict":
        return f"{names.get(body['item_code'], body['item_code'])} → {body['state']}"
    if kind == "alert":
        return body["message"]
    if kind == "assist":
        return f"{body['assist_type']}: {body['text']}"
    return kind


def build(
    session_id: str, events: list[dict[str, Any]], engine: Engine, pack: RulePack, doc: dict | None
) -> dict[str, Any]:
    started = datetime.fromisoformat(
        next(e for e in events if e["kind"] == "session_started")["occurred_at"]
    )
    state = engine.fold(events)
    summary = engine.summarize(state, pack, events)
    names = {it.code: it.name for it in pack.items}
    superseded = {e["supersedes"] for e in events if e.get("supersedes")}
    live = [e for e in events if e["event_id"] not in superseded]

    evidence_of = {
        (e["verdict"]["item_code"], e["verdict"]["axis"]): e["event_id"]
        for e in live
        if e["kind"] == "verdict" and e["verdict"].get("evidence")
    }

    def axis_rows(axis: str) -> list[dict[str, Any]]:
        return [
            {
                "item_code": s.item_code,
                "name": names.get(s.item_code, s.item_code),
                "state": s.state,
                "decided_by": s.decided_by,
                "missing_elements": list(s.missing_elements),
                "waive_reason": s.waive_reason,
                "evidence_ref": evidence_of.get((s.item_code, axis)),
            }
            for s in state.items
            if s.axis == axis
        ]

    return {
        "session_id": session_id,
        "pack_version": pack.pack_version,
        "generated_at": datetime.now(UTC),
        # 출처는 상시 표기 대상이다. 어느 문서 어느 시점 기준인지 리포트에 남는다
        "sources": (doc or {}).get("sources", []),
        "sections": {
            "summary": summary,
            "omission": axis_rows("omission"),
            "commission": axis_rows("commission"),
            "comprehension": axis_rows("comprehension"),
            # 기획 10.3 "위험 신호는 경보 + 확인 기록까지" 의 자리.
            # 다른 종류의 경보는 timeline 에 들어간다
            "risk_signals": [
                {
                    "event_id": e["event_id"],
                    "severity": e["alert"]["severity"],
                    "message": e["alert"]["message"],
                    "acknowledged": e["alert"].get("acknowledged", False),
                    "t_ms": _t_ms(e, started),
                }
                for e in live
                if e["kind"] == "alert" and e["alert"]["alert_type"] == "risk_signal"
            ],
            "timeline": [
                {
                    "t_ms": _t_ms(e, started),
                    "kind": e["kind"],
                    "label": _label(e, names),
                    "evidence_ref": e["event_id"] if e[e["kind"]].get("evidence") else None,
                }
                for e in live
                if e["kind"] in ("utterance", "verdict", "alert", "assist")
            ],
        },
        "disclaimer": DISCLAIMER,
    }
