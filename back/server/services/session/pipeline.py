"""발화 한 건의 유일한 합류점. 네 모드(live·replay·text·trace)가 전부 여기로 온다.

submit_utterance: 저장(발화) → judge → apply → map → persist → publish.
refine(비동기 L3)은 refiner.py 가 생기면 같은 순서로 큐를 통해 붙는다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from contracts.engine_contract import Engine, JudgeResult, Utterance
from server.mapping import event_to_s2c, payload_to_event
from server.services.event import envelope
from server.services.event.store import EventStore
from server.services.session import chains
from server.services.session.projection import NullSessionProjection, SessionProjection
from server.services.session.registry import Session

Publish = Callable[[dict[str, Any]], Awaitable[Any]]


class Pipeline:
    def __init__(
        self,
        engine: Engine,
        store: EventStore,
        projection: SessionProjection | None = None,
    ) -> None:
        self.engine = engine
        self.store = store
        # sessions 투영은 이벤트를 접어 만든 파생물이다. 없어도 정본은 온전하다
        self.projection = projection or NullSessionProjection()

    def _wrap(self, session: Session, kind: str, body: dict, supersedes: str | None = None):
        return envelope.wrap(
            session_id=session.session_id,
            pack_version=session.pack.pack_version,
            seq_in_session=session.take_seq(),
            kind=kind,
            body=body,
            supersedes=supersedes,
        )

    def _persist(self, session: Session, kind: str, body: dict, supersedes: str | None = None):
        event = self._wrap(session, kind, body, supersedes)
        self.store.append(event)
        return event

    async def submit_utterance(
        self, session: Session, utterance: Utterance, publish: Publish
    ) -> JudgeResult:
        ev = self._persist(session, "utterance", payload_to_event.utterance_body(utterance))
        utterance = replace(utterance, utterance_id=ev["event_id"])
        await publish(event_to_s2c.from_event(ev, session.state))

        result = self.engine.judge(utterance, session.pack, session.state)
        await self.apply_result(session, result, publish)
        return result

    async def apply_result(self, session: Session, result: JudgeResult, publish: Publish) -> None:
        """한 판정에서 나온 이벤트를 한 번에 저장하고, 저장된 뒤에 내보낸다.

        낱개로 저장하면 중간에 실패했을 때 verdict 만 남고 alert 는 없는 절반짜리 기록이
        생긴다. 감사의 원본이 절반이면 리포트도 절반이 된다.
        """
        if not (result.verdicts or result.alerts or result.assists):
            return
        session.state = self.engine.apply(session.state, result)
        pending: list[tuple[dict, int]] = []  # (이벤트, assist 회차)

        for v in result.verdicts:
            key = (v.item_code, v.axis)
            event = self._wrap(
                session,
                "verdict",
                payload_to_event.verdict_body(v),
                supersedes=session.latest_event_by_item.get(key),
            )
            session.latest_event_by_item[key] = event["event_id"]
            pending.append((event, 1))

        for a in result.alerts:
            pending.append((self._wrap(session, "alert", payload_to_event.alert_body(a)), 1))

        for s in result.assists:
            body = payload_to_event.assist_body(s)
            key = chains.assist_key(body)
            supersedes, ver = session.assist_ver(key)
            event = self._wrap(session, "assist", body, supersedes=supersedes)
            session.latest_assist[key] = (event["event_id"], ver)
            pending.append((event, ver))

        self.store.append_many([e for e, _ in pending])
        for event, ver in pending:
            await publish(event_to_s2c.from_event(event, session.state, ver))
        if result.verdicts:
            await publish(event_to_s2c.progress(session.pack, session.state))

    def start(self, session: Session, mode: str, product: dict, customer_type: str) -> dict:
        event = self._persist(
            session,
            "session_started",
            {
                "mode": mode,
                "product": product,
                "customer_profile": {"type": customer_type},
                "item_count": len(session.pack.required_items()),
            },
        )
        self.projection.opened(event)
        return event

    def end(self, session: Session, duration_ms: int, reason: str = "normal") -> dict:
        # trace 는 원본 세션의 이벤트로 요약한다. 자기 봉투만으로는 상담 내용이 없다
        events = self.store.of_session(session.source_session_id or session.session_id)
        summary = self.engine.summarize(session.state, session.pack, events)
        event = self._persist(
            session,
            "session_ended",
            {"reason": reason, "duration_ms": duration_ms, "summary": summary},
        )
        self.projection.ended(event)
        return event
