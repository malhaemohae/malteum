"""저장 이벤트에서 갱신 사슬을 되살린다.

계약은 갱신을 `supersedes` 로 잇는다. 그 사슬의 재료(항목별 마지막 event_id, assist 의
회차)는 서버가 메모리에 들고 있는데, 재접속하면 그 메모리가 없다. 저장된 이벤트가
정본이므로 여기서 다시 만든다. **재접속 복구와 trace 재생이 같은 함수를 써야** 두
경로가 다른 `ver` 을 내지 않는다.

verdict 의 `ver` 은 engine.fold 가 상태에 담아 주므로 여기서 다루지 않는다.
assist 는 상태에 남지 않아 여기서 센다.
"""

from __future__ import annotations

from typing import Any

# 같은 assist 로 보는 기준. contracts/README: 제시할 때 outcome=null 로 내고
# 은행원이 그 표현을 썼는지 확인되면 outcome 을 채워 다시 발행한다
AssistKey = tuple[str, str | None]


def assist_key(body: dict[str, Any]) -> AssistKey:
    return (body["assist_type"], body.get("item_code"))


def by_seq(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=lambda e: e["seq_in_session"])


def latest_verdicts(events: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """(item_code, axis) → 마지막 verdict 의 event_id. 다음 판정이 이것을 supersede 한다."""
    return {
        (e["verdict"]["item_code"], e["verdict"]["axis"]): e["event_id"]
        for e in by_seq(events)
        if e["kind"] == "verdict"
    }


def latest_assists(events: list[dict[str, Any]]) -> dict[AssistKey, tuple[str, int]]:
    """assist 종류별 마지막 (event_id, ver). 다음 발행이 ver+1 이 된다."""
    out: dict[AssistKey, tuple[str, int]] = {}
    for e in by_seq(events):
        if e["kind"] != "assist":
            continue
        key = assist_key(e["assist"])
        out[key] = (e["event_id"], out.get(key, ("", 0))[1] + 1)
    return out


def assist_versions(events: list[dict[str, Any]]) -> dict[str, int]:
    """event_id → 그 assist 가 몇 번째 발행인지. 화면은 ver 이 큰 것만 채택한다."""
    counted: dict[AssistKey, int] = {}
    out: dict[str, int] = {}
    for e in by_seq(events):
        if e["kind"] != "assist":
            continue
        key = assist_key(e["assist"])
        counted[key] = counted.get(key, 0) + 1
        out[e["event_id"]] = counted[key]
    return out
