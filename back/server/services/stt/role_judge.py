"""실물 `RoleJudge` (LiteLLM). 화자분리 번호 하나에 역할을 붙인다.

문장 하나의 화자를 맞히는 것이 아니라 **번호 하나의 정체**를 정한다. 그래서 그 번호의
발화 몇 개와, 이미 역할이 정해진 번호들의 최근 발화를 함께 준다 — 같은 상담 안에서
대조할 상대가 있으면 "이쪽이 설명하는 쪽" 이 훨씬 또렷해진다.

프롬프트 단서는 `scripts/speaker_infer_check.py` 실측에서 가져왔다(CTX-005). 특히
"~해 주세요 가 화자를 정하지 않는다 · 돈의 주인은 고객이다 · 은행원은 송금처를 먼저
정하지 않는다" 세 줄이 8b 모델에서 "해지한 돈은 딸이 알려준 계좌로 보내 주세요" 를
은행원으로 뒤집던 오답을 없앴다. 그 문장이 위험 신호 경보의 유일한 입구다.

LiteLLM 은 동기 호출이라 스레드로 넘긴다. 화자 단계는 답을 기다리는 동안 발화를
잠정 라벨로 흘려보내므로, 여기서 막혀도 상담은 멈추지 않는다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import litellm

from engine.adapters.llm.litellm import register
from server.services.stt.speaker import RoleRequest, RoleVerdict

TOOL_NAME = "assign_role"

SYSTEM_PROMPT = """당신은 은행 창구 상담 녹취에서 화자 분리가 매긴 번호의 정체를 가려낸다.
번호 하나가 낸 발화 몇 개와, 이미 역할이 정해진 번호들의 최근 발화를 함께 받는다.
그 번호가 은행원(teller)인지 고객(customer)인지, 둘 다 아닌 제3자(other)인지 정하고
반드시 `assign_role` 툴로 답한다.

단서
- 은행원: 상품 조건·이율·세금·수수료·권리를 설명하고 안내한다. "안내드리겠습니다",
  "적용됩니다", "고객님", "준비해 주세요", "죄송합니다, 정정하겠습니다" 처럼 설명·안내·
  정정·요청하는 말.
- 고객: 자기 상황을 말하고, 묻고, 되묻고, 이해했다고 되짚고, 결정을 말한다. "제 조건이면",
  "그게 뭐예요?", "그렇다는 거네요", "그냥 해지할게요", "걱정되네요" 처럼 사정·질문·확인·
  결정하는 말.
- "~해 주세요" 는 화자를 정하지 않는다. 누가 누구에게 시키는지를 본다.
- 돈의 주인은 고객이다. 은행원은 고객의 돈을 어디로 보낼지 먼저 정하지 않는다.
  "그 돈은 ~로 보내 주세요" 는 결정을 말하는 것이므로 고객이다.
- 이미 역할이 정해진 번호와 말투가 같은 쪽이면 화자 분리가 한 사람을 두 번호로 가른
  것이다. 같은 역할로 답한다. 번호가 셋이라고 사람이 셋인 것은 아니다.
- other 는 상담 당사자가 아닌 소리에만 쓴다. 지나가는 사람, 안내 방송, 잡음.
  확신이 없으면 other 대신 낮은 confidence 로 teller·customer 중 하나를 고른다."""

TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "화자 분리 번호 하나의 역할을 정한다",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "enum": ["teller", "customer", "other"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string", "description": "근거 한 문장"},
            },
            "required": ["role", "confidence"],
            "additionalProperties": False,
        },
    },
}


class LiteLlmRoleJudge:
    def __init__(
        self,
        model: str,
        *,
        provider: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model = register(model, provider, "chat")
        self.api_key = api_key
        self.temperature = temperature
        self.timeout_s = timeout_s
        self.extra_body = extra_body

    async def decide(self, request: RoleRequest) -> RoleVerdict:
        return await asyncio.to_thread(self._decide, request)

    def _decide(self, request: RoleRequest) -> RoleVerdict:
        body = {
            "target": {"speaker_id": request.speaker_id, "utterances": list(request.recent)},
            "known": [
                {"speaker_id": k.speaker_id, "role": k.role, "utterances": list(k.recent)}
                for k in request.known
            ],
        }
        resp = litellm.completion(
            model=self.model,
            api_key=self.api_key,
            temperature=self.temperature,
            timeout=self.timeout_s,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False, indent=1)},
            ],
            tools=[TOOL],
            tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            extra_body=self.extra_body,
        )
        args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
        role = args["role"]
        if role not in ("teller", "customer", "other"):
            raise ValueError(f"모르는 역할: {role!r}")
        return RoleVerdict(role, float(args["confidence"]), args.get("reason", ""))
