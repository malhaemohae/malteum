"""assist 4종. 기능 ①⑩(역질문·텍스트 질의) · ⑥-B(재진술) · ②(브리핑) · ④(서류).

**server 에는 assist 구현이 없다**(`server/AGENTS.md`). 여기는 engine 을 부르고 그 결과를
`apply_result` 에 흘려보내는 일만 한다. 저장·`supersedes`·`ver`·전송은 판정과 같은 길을
그대로 쓴다. 계약이 assist 에도 supersede 패턴을 쓴다고 정했기 때문이다.

근거를 못 찾으면 engine 이 `None` 을 돌려준다(P4). 그때 무엇을 보낼지가 계약에 없다 —
s2c `assist` 는 `text` 가 required 라 "근거 없음" 을 담지 못하고, error enum 에도 맞는
코드가 없다. 지금은 error 로 알리고 팀 결정을 기다린다.
"""

from __future__ import annotations

import asyncio

from contracts.engine_contract import AssistPayload, JudgeResult
from server.services.session.pipeline import Pipeline, Publish
from server.services.session.registry import Session

NO_BASIS = "규정에서 근거를 찾지 못했습니다."


async def _publish(
    session: Session, pipeline: Pipeline, payload: AssistPayload | None, publish: Publish
) -> str | None:
    """만들어진 assist 를 판정과 같은 길로 내보낸다. 못 만들었으면 사유를 돌려준다."""
    if payload is None:
        return NO_BASIS
    await pipeline.apply_result(session, JudgeResult(assists=(payload,)), publish)
    return None


async def ask(session: Session, pipeline: Pipeline, question: str, publish: Publish) -> str | None:
    """기능 ⑩ 텍스트 질의. 계약: 질문은 발화가 아니므로 utterance 로 저장하지 않는다.

    남는 것은 답변 assist 하나뿐이고, 무엇을 물었는지는 그 답의 근거로 읽힌다.
    """
    payload = await asyncio.to_thread(pipeline.engine.answer, question, session.pack, session.state)
    return await _publish(session, pipeline, payload, publish)


async def assist_request(
    session: Session, pipeline: Pipeline, assist_type: str, publish: Publish
) -> str | None:
    """기능 ⑥-B·②·④ 의 수동 버튼. 자동 트리거가 놓쳤을 때 사람이 보완한다(P3 방향).

    계약의 `item_code` 는 아직 쓰지 않는다. engine 의 rephrase·documents·briefing 표면이
    그 인자를 받지 않아, 여기서 받아 두면 무시되는 값이 하나 생긴다.
    """
    engine = pipeline.engine
    if assist_type == "rephrase":
        source = session.last_teller_utterance
        if source is None:
            # 다시 말할 대상이 없다. 상담 시작 전이거나 고객만 말한 상태다
            return "다시 말할 직전 발화가 없습니다."
        payload = await asyncio.to_thread(engine.rephrase, source, session.pack, session.state)
    elif assist_type == "documents":
        payload = await asyncio.to_thread(engine.documents, session.pack, session.state)
    elif assist_type == "briefing":
        payload = await asyncio.to_thread(
            engine.briefing, session.pack, session.state.customer_type
        )
    else:  # 스키마가 먼저 거르지만, enum 이 늘었을 때 조용히 통과하지 않게 한다
        return f"알 수 없는 assist_type 입니다: {assist_type}"
    return await _publish(session, pipeline, payload, publish)
