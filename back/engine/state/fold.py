"""이벤트 열 → 상태. trace 재생과 리포트가 같은 함수를 쓴다. supersede 된 이벤트는 건너뛴다.

입력은 events.schema.json 을 만족하는 dict 열(저장물 그대로). engine 은 pydantic 모델을 모른다.
"""

from __future__ import annotations

from collections.abc import Sequence

from contracts.engine_contract import ItemState, Utterance
from engine.types import SessionState

RECENT_UTTERANCES = 8


def fold(events: Sequence[dict]) -> SessionState:
    started = next(e for e in events if e["kind"] == "session_started")
    superseded = {e["supersedes"] for e in events if e.get("supersedes")}

    items: dict[tuple[str, str], ItemState] = {}
    ver: dict[tuple[str, str], int] = {}
    utterances: list[Utterance] = []
    alerts = 0
    for e in sorted(events, key=lambda e: e["seq_in_session"]):
        kind = e["kind"]
        if kind == "verdict":
            v = e["verdict"]
            key = (v["item_code"], v["axis"])
            ver[key] = ver.get(key, 0) + 1
            if e["event_id"] in superseded:
                continue
            items[key] = ItemState(
                item_code=v["item_code"],
                axis=v["axis"],
                state=v["state"],
                decided_by=v["decided_by"],
                ver=ver[key],
                missing_elements=tuple(v.get("missing_elements", ())),
                waive_reason=v.get("waive_reason"),
            )
        elif kind == "utterance":
            u = e["utterance"]
            utterances.append(
                Utterance(
                    utterance_id=e["event_id"],
                    speaker=u["speaker"],
                    text=u["text"],
                    t_ms=u["t_ms"],
                    duration_ms=u.get("duration_ms"),
                    stt_confidence=u.get("stt_confidence"),
                    speaker_confidence=u.get("speaker_confidence"),
                )
            )
        elif kind == "alert":
            alerts += 1

    profile = started["session_started"].get("customer_profile") or {}
    return SessionState(
        session_id=started["session_id"],
        pack_version=started["pack_version"],
        mode=started["session_started"]["mode"],
        customer_type=profile.get("type", "general"),
        items=tuple(items.values()),
        recent_utterances=tuple(utterances[-RECENT_UTTERANCES:]),
        alert_count=alerts,
    )
