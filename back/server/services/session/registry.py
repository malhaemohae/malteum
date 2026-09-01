"""활성 세션 메모리. 상태·팩·seq_in_session·갱신 사슬(supersedes 재료).

**메모리는 정본이 아니다.** 서버가 재시작되면 여기 있던 것이 사라지지만 이벤트는 남아
있다. 계약이 `hello.session_id` 를 "이어 붙일 세션" 이라고 정의하므로, 저장된 이벤트가
있는 session_id 로 다시 붙으면 새로 만들지 않고 접어서 되살린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal

from contracts.engine_contract import Engine, Mode, RulePack, SessionState, Utterance
from server.services.event.envelope import new_id
from server.services.event.store import EventStore
from server.services.session import chains


def _now() -> datetime:
    return datetime.now(UTC)


def _started_at(events: list[dict]) -> datetime:
    """되살린 세션의 t_ms 원점. session_started 의 봉투 시각이다.

    그것이 없으면(있을 수 없지만 저장이 부분적으로 깨진 경우) 가장 이른 이벤트로 물러선다.
    지금 시각으로 물러서면 이어 붙인 발화가 0 부터 매겨져 앞부분과 겹친다.
    """
    times = [
        datetime.fromisoformat(e["occurred_at"]).astimezone(UTC)
        for e in events
        if e["kind"] == "session_started"
    ] or [datetime.fromisoformat(e["occurred_at"]).astimezone(UTC) for e in events]
    return min(times) if times else _now()


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
    # t_ms 의 원점. 계약이 "세션 시작 기준" 이라 연결이 아니라 세션이 들고 있어야 한다.
    # 되살린 세션은 session_started.occurred_at 을 도로 가져온다
    started_at: datetime = field(default_factory=_now)
    # rephrase(⑥-B)가 다시 말할 대상. `SessionState.recent_utterances` 는 fold 만 채우고
    # 실시간 경로는 apply(state, result) 라 발화를 못 받는다. 받는 쪽이 M1 이라 여기 둔다
    last_teller_utterance: Utterance | None = None

    def take_seq(self) -> int:
        seq, self.next_seq = self.next_seq, self.next_seq + 1
        return seq

    def elapsed_ms(self) -> int:
        """세션 시작부터 지금까지. 봉투의 occurred_at 과 같은 시계를 쓴다.

        단조 시계가 아니라 벽시계인 이유는 재접속 때문이다. 프로세스가 죽었다 살아나면
        단조 시계의 원점이 사라지고, 그러면 이어 붙인 세션의 t_ms 가 0 부터 다시 매겨져
        앞부분과 겹친다. 겹친 t_ms 로는 발화 재생(C축 DoD)이 어느 지점인지 못 짚는다.
        """
        return max(0, int((_now() - self.started_at).total_seconds() * 1000))

    def assist_ver(self, key: chains.AssistKey) -> tuple[str | None, int]:
        """다음 발행의 (supersedes, ver). 첫 발행이면 (None, 1)."""
        previous = self.latest_assist.get(key)
        return (previous[0], previous[1] + 1) if previous else (None, 1)


class SessionRegistry:
    def __init__(self, engine: Engine, store: EventStore) -> None:
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
            started_at=_started_at(events),
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
