"""append-only 이벤트 저장. 지금은 메모리. postgres 구현은 database/ 가 생기면 같은 표면으로."""

from __future__ import annotations

from typing import Any, Protocol

from server.generated import events as gen


class EventStore(Protocol):
    def append(self, event: dict[str, Any]) -> None: ...
    def of_session(self, session_id: str) -> list[dict[str, Any]]: ...


class MemoryEventStore:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def append(self, event: dict[str, Any]) -> None:
        gen.event_adapter.validate_python(event)  # 저장물은 스키마를 벗어나지 않는다
        self._events.append(event)

    def of_session(self, session_id: str) -> list[dict[str, Any]]:
        return [e for e in self._events if e["session_id"] == session_id]
