"""저장 이벤트(dict) → s2c 메시지 본문(dict, seq 없음). Connection.send 가 seq 를 붙인다."""

from __future__ import annotations

from typing import Any

from engine.types import RulePack, SessionState


def ready(session_id: str, pack: RulePack, state: SessionState, mode: str) -> dict[str, Any]:
    items = []
    for it in pack.items:
        axis = "commission" if it.type == "forbidden" else "omission"
        s = state.state_of(it.code, axis)
        if s is None:  # reference·risk 항목은 체크리스트에 없다
            continue
        item: dict[str, Any] = {
            "item_code": it.code,
            "name": it.name,
            "axis": s.axis,
            "state": s.state,
            "required": it.type == "required",
        }
        if it.plain_language:
            item["plain_language"] = list(it.plain_language)
        items.append(item)
    return {
        "t": "ready",
        "session_id": session_id,
        "pack_version": pack.pack_version,
        "mode": mode,
        "items": items,
    }


def from_event(event: dict[str, Any], state: SessionState) -> dict[str, Any] | None:
    kind = event["kind"]
    body = event[kind]
    if kind == "utterance":
        return {"t": "utterance", "event_id": event["event_id"], **body}
    if kind == "verdict":
        item = next(
            s for s in state.items if (s.item_code, s.axis) == (body["item_code"], body["axis"])
        )
        out = {
            "t": "verdict",
            "event_id": event["event_id"],
            "item_code": body["item_code"],
            "axis": body["axis"],
            "state": body["state"],
            "ver": item.ver,
            "decided_by": body["decided_by"],
        }
        if body.get("missing_elements"):
            out["missing_elements"] = body["missing_elements"]
        if body.get("evidence"):
            out["evidence_ref"] = event["event_id"]
        return out
    if kind == "alert":
        keys = ("alert_type", "severity", "message", "item_code", "comparison")
        out = {"t": "alert", "event_id": event["event_id"]}
        out.update({k: body[k] for k in keys if k in body})
        if body.get("evidence"):
            out["evidence_ref"] = event["event_id"]
        return out
    if kind == "assist":
        out = {
            "t": "assist",
            "event_id": event["event_id"],
            "assist_type": body["assist_type"],
            "text": body["text"],
            "ver": 1,
        }
        for k in ("item_code", "outcome"):
            if k in body:
                out[k] = body[k]
        if body.get("evidence"):
            out["evidence_ref"] = event["event_id"]
        return out
    return None


def progress(pack: RulePack, state: SessionState) -> dict[str, Any]:
    required = pack.required_items()
    by_code = {s.item_code: s.state for s in state.items if s.axis == "omission"}
    return {
        "t": "progress",
        "met": sum(1 for it in required if by_code.get(it.code) == "met"),
        "partial": sum(1 for it in required if by_code.get(it.code) == "partial"),
        "items_total": len(required),
        "remaining": [it.name for it in required if by_code.get(it.code) in ("unmet", "partial")],
        "term_density": state.term_density,
    }
