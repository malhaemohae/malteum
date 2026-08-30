"""활성 세션 메모리. 상태·팩·seq_in_session·갱신 사슬(supersedes 재료).

**메모리는 정본이 아니다.** 서버가 재시작되면 여기 있던 것이 사라지지만 이벤트는 남아
있다. 계약이 `hello.session_id` 를 "이어 붙일 세션" 이라고 정의하므로, 저장된 이벤트가
있는 session_id 로 다시 붙으면 새로 만들지 않고 접어서 되살린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from contracts.engine_contract import Mode
from engine.engine import RuleEngine
from engine.types import RulePack, SessionState
from server.services.event.envelope import new_id
from server.services.event.store import EventStore
from server.services.session import chains


@dataclass
class Session:
    session_id: str
    pack: RulePack
    state: SessionState
    mode: Mode = "text"
    # mode=trace 일 때 재생할 원본 세션. 계약상 POST /sessions 로만 지정된다
    source_session_id: str | None = None
    next_seq: int = 0
    latest_event_by_item: dict[tuple[str, str], str] = field(default_factory=dict)
    latest_assist: dict[chains.AssistKey, tuple[str, int]] = field(default_factory=dict)
    # 저장된 이벤트에서 되살린 세션. session_started 를 다시 쓰면 안 된다
    restored: bool = False
    t0_ms: int = 0

    def take_seq(self) -> int:
        seq, self.next_seq = self.next_seq, self.next_seq + 1
        return seq

    def assist_ver(self, key: chains.AssistKey) -> tuple[str | None, int]:
        """다음 발행의 (supersedes, ver). 첫 발행이면 (None, 1)."""
        previous = self.latest_assist.get(key)
        return (previous[0], previous[1] + 1) if previous else (None, 1)


class SessionRegistry:
    def __init__(self, engine: RuleEngine, store: EventStore) -> None:
        self.engine = engine
        self.store = store
        self._packs: dict[str, RulePack] = {}
        self._sessions: dict[str, Session] = {}

    def pack(self, pack_version: str) -> RulePack:
        if pack_version not in self._packs:
            self._packs[pack_version] = self.engine.load_pack(pack_version)
        return self._packs[pack_version]

    def open(
        self,
        pack_version: str,
        mode: Mode,
        customer_type: Literal["general", "professional"] = "general",
        session_id: str | None = None,
        source_session_id: str | None = None,
    ) -> Session:
        if session_id:
            live = self._sessions.get(session_id)
            if live is not None:
                return live
            stored = self.store.of_session(session_id)
            if stored:
                return self._restore(session_id, stored, source_session_id)

        session_id = session_id or new_id()
        pack = self.pack(pack_version)
        state = self.engine.initial_state(session_id, pack, mode, customer_type)
        session = Session(
            session_id=session_id,
            pack=pack,
            state=state,
            mode=mode,
            source_session_id=source_session_id,
        )
        self._sessions[session_id] = session
        return session

    def _restore(
        self, session_id: str, events: list[dict], source_session_id: str | None
    ) -> Session:
        """이벤트를 접어 세션을 되살린다. 새 이벤트를 만들지 않는다."""
        folded = self.engine.fold(events)
        pack = self.pack(folded.pack_version)
        # fold 는 판정이 있었던 항목만 담는다. 판정 전 항목까지 보이도록 출발 상태에 덮는다
        state = self.engine.initial_state(session_id, pack, folded.mode, folded.customer_type)
        judged = {(i.item_code, i.axis): i for i in folded.items}
        merged = tuple(judged.pop((i.item_code, i.axis), i) for i in state.items)
        state = replace(
            folded, items=merged + tuple(judged.values())
        )  # fold 에만 있는 축(comprehension 등)도 잃지 않는다
        session = Session(
            session_id=session_id,
            pack=pack,
            state=state,
            mode=folded.mode,
            source_session_id=source_session_id,
            next_seq=max(e["seq_in_session"] for e in events) + 1,
            latest_event_by_item=chains.latest_verdicts(events),
            latest_assist=chains.latest_assists(events),
            restored=True,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
