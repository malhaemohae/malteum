"""활성 세션 메모리. 상태·팩·seq_in_session·항목별 최신 event_id(supersedes 재료)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.engine_contract import Mode
from engine.engine import RuleEngine
from engine.types import RulePack, SessionState
from server.services.event.envelope import new_id


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
    t0_ms: int = 0

    def take_seq(self) -> int:
        seq, self.next_seq = self.next_seq, self.next_seq + 1
        return seq


class SessionRegistry:
    def __init__(self, engine: RuleEngine) -> None:
        self.engine = engine
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

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
