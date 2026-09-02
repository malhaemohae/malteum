"""L3 보정 큐. 한 세션의 보정을 한 번에 하나씩 돌린다.

계약(`contracts/README.md` 이름·번호 규칙): `judge()` 가 `needs_refine=True` 를
돌려주면 M1 이 `refine()` 을 비동기로 예약한다. False 면 부르지 않는다.

**직렬로 도는 이유.** 판정 이벤트의 `seq_in_session`·`supersedes`·assist `ver` 는
세션 단위로 매긴다(`Session.take_seq`·`latest_event_by_item`·`latest_assist`).
보정 둘이 동시에 `apply_result` 에 들어가면 같은 항목의 supersede 사슬이 엇갈리고
seq 가 겹친다. 화면이 기다리지 않는다는 것과 서버가 동시에 처리한다는 것은 다르다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from contracts.engine_contract import Utterance
from server.services.session.pipeline import Pipeline, Publish
from server.services.session.registry import Session

OnError = Callable[[Exception], Awaitable[None]]


class Refiner:
    """발화 하나에 보정 하나. 연결이 닫히면 남은 것은 버린다."""

    def __init__(
        self, session: Session, pipeline: Pipeline, publish: Publish, on_error: OnError
    ) -> None:
        self.session = session
        self.pipeline = pipeline
        self.publish = publish
        self.on_error = on_error
        self.queue: asyncio.Queue[Utterance] = asyncio.Queue()
        self.worker: asyncio.Task | None = None

    def schedule(self, utterance: Utterance) -> None:
        """큐에 넣고 즉시 돌아온다. 확정 발화의 화면 반영이 L3 를 기다리지 않는다(11.1)."""
        if self.worker is None:
            self.worker = asyncio.create_task(self._run())
        self.queue.put_nowait(utterance)

    async def _run(self) -> None:
        while True:
            utterance = await self.queue.get()
            try:
                await self.pipeline.refine(self.session, utterance, self.publish)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  보정 실패가 상담을 끊지 않게 한다
                await self.on_error(e)
            finally:
                self.queue.task_done()

    async def aclose(self) -> None:
        if self.worker is None:
            return
        self.worker.cancel()
        with suppress(asyncio.CancelledError):
            await self.worker
