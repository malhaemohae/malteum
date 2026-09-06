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
    "이 리포트의 판정은 두 가지를 봅니다. 안내해야 할 것을 빠뜨렸는지, "
    "해서는 안 될 말을 했는지입니다. 고객이 이해했는지 남긴 기록은 "
    "상담을 돌아보라고 모아 둔 참고 자료이고, 판정의 근거가 아닙니다."
)


# 금지·숫자 표에 행으로 붙이는 경보 종류. 위험 신호는 자기 섹션(risk_signals)이 따로 있다
COMMISSION_ALERTS = ("number_mismatch", "forbidden_phrase")


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
        # 종류를 앞에 붙인다. 메시지만 남기면 무슨 경보였는지 표에서 안 보인다
        return f"{body['alert_type']}: {body['message']}"
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
        rows = [
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
        if axis == "omission":
            # 끝까지 한 번도 언급되지 않은 필수 항목은 판정 이벤트가 없어 상태에 없다.
            # 요약은 그것을 unmet 으로 세므로(summary.py) 리포트 표에도 같은 행이 있어야 한다
            judged = {r["item_code"] for r in rows}
            rows += [
                {
                    "item_code": it.code,
                    "name": it.name,
                    "state": "unmet",
                    "decided_by": None,
                    "missing_elements": [],
                    "waive_reason": None,
                    "evidence_ref": None,
                }
                for it in pack.required_items()
                if it.code not in judged
            ]
        return rows

    # 기획 §10 "리포트에 위반 1건 + 위험 신호 기록". 금지 표현·숫자 오류 경보는 항목 상태
    # (violated)와 별개로 발생하므로, 상태 행만 두면 숫자 경보가 리포트의 금지·숫자 표에서
    # 사라진다(2026-09-06 실측: 경보 2건인 상담의 commission 표가 비어 있었다). 경보를
    # 같은 표에 행으로 붙인다. 계약은 commission 을 object 배열로만 정해 두었다
    commission_alerts = [
        {
            "kind": "alert",
            "event_id": e["event_id"],
            "alert_type": e["alert"]["alert_type"],
            "item_code": e["alert"].get("item_code"),
            "name": names.get(e["alert"].get("item_code") or "", e["alert"].get("item_code") or ""),
            "message": e["alert"]["message"],
            "severity": e["alert"]["severity"],
            "acknowledged": e["alert"].get("acknowledged", False),
            "comparison": e["alert"].get("comparison"),
            "t_ms": _t_ms(e, started),
            "evidence_ref": e["event_id"] if e["alert"].get("evidence") else None,
        }
        for e in live
        if e["kind"] == "alert" and e["alert"]["alert_type"] in COMMISSION_ALERTS
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
            "commission": axis_rows("commission") + commission_alerts,
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
