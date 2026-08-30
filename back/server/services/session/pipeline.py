"""발화 한 건의 유일한 합류점. 네 모드(live·replay·text·trace)가 전부 여기로 온다.

submit_utterance: 저장(발화) → judge → apply → map → persist → publish.
refine(비동기 L3)은 refiner.py 가 생기면 같은 순서로 큐를 통해 붙는다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from contracts.engine_contract import Engine, JudgeResult, Utterance, VerdictPayload
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

    async def human_verdict(
        self,
        session: Session,
        item_code: str,
        state: str,
        publish: Publish,
        waive_reason: str | None = None,
    ) -> None:
        """사람이 직접 찍은 판정. 엔진을 거치지 않는다.

        기획 7.1 ⑪: 수동 체크리스트는 STT 없이 도는 3층 폴백이고 **사람 결정은 엔진이
        못 뒤집는다.** 축은 omission 이다. 계약의 상태 enum 상 waived 가 그 축에만 있고,
        체크리스트가 세는 것도 필수 고지 항목이다.
        """
        payload = VerdictPayload(
            item_code=item_code,
            axis="omission",
            state=state,  # type: ignore[arg-type]  계약 enum 은 스키마가 검증한다
            decided_by="human",
            waive_reason=waive_reason,
        )
        key = (item_code, "omission")
        event = self._wrap(
            session,
            "verdict",
            payload_to_event.verdict_body(payload),
            supersedes=session.latest_event_by_item.get(key),
        )
        session.latest_event_by_item[key] = event["event_id"]
        self.store.append(event)
        session.state = self.engine.apply(session.state, JudgeResult(verdicts=(payload,)))
        await publish(event_to_s2c.from_event(event, session.state))
        await publish(event_to_s2c.progress(session.pack, session.state))

    async def acknowledge(self, session: Session, alert_ref: str, publish: Publish) -> bool:
        """경보 확인 기록. 같은 alert 를 acknowledged=true 로 다시 발행한다.

        기획 10.3: 위험 신호는 "경보 + 확인 기록까지" 가 MVP 범위다. append-only 라
        원본을 고치지 않고 supersedes 로 잇는다.
        """
        events = self.store.of_session(session.session_id)
        original = next(
            (e for e in events if e["event_id"] == alert_ref and e["kind"] == "alert"), None
        )
        if original is None:
            return False
        body = {**original["alert"], "acknowledged": True}
        event = self._wrap(session, "alert", body, supersedes=alert_ref)
        self.store.append(event)
        await publish(event_to_s2c.from_event(event, session.state))
        return True

    def previous_state(self, session: Session, item_code: str) -> str | None:
        """지금 판정이 supersede 한 앞선 판정의 상태. mark_met 되돌리기가 쓴다."""
        head_id = session.latest_event_by_item.get((item_code, "omission"))
        if head_id is None:
            return None
        events = {e["event_id"]: e for e in self.store.of_session(session.session_id)}
        head = events.get(head_id)
        previous = events.get(head.get("supersedes") or "") if head else None
        return previous["verdict"]["state"] if previous else None

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
