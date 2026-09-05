"""저장 이벤트(dict) → s2c 메시지 본문(dict, seq 없음). Connection.send 가 seq 를 붙인다."""

from __future__ import annotations

from typing import Any

from contracts.engine_contract import RulePack, SessionState


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


def from_event(
    event: dict[str, Any], state: SessionState, assist_ver: int = 1
) -> dict[str, Any] | None:
    kind = event["kind"]
    body = event[kind]
    if kind == "utterance":
        # 이벤트 본문에는 duration_ms·stt_confidence·speaker_confidence 가 더 있다.
        # 화면이 쓰는 넷만 보낸다 (계약: 이벤트를 그대로 전송하지 않는다)
        return {
            "t": "utterance",
            "event_id": event["event_id"],
            "speaker": body["speaker"],
            "text": body["text"],
            "t_ms": body["t_ms"],
        }
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
            # 계약: 같은 assist 를 outcome 채워 다시 발행한다. 화면은 ver 이 큰 것만 채택한다
            "ver": assist_ver,
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
        # 판정이 한 번도 없는 필수 항목은 상태에 없다. 요약(summary.py)이 그것을 unmet 으로
        # 세듯 여기서도 남은 항목이다 — 빼면 화면의 남은 목록과 종료 요약의 unmet 수가 어긋난다
        "remaining": [
            it.name for it in required if by_code.get(it.code, "unmet") in ("unmet", "partial")
        ],
        "term_density": state.term_density,
    }
