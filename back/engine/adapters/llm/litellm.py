"""실물 L3. LiteLLM 으로 provider(openrouter·anthropic·openai …) 모델에 tool calling 을 강제한다.

model 은 provider 공식 표기 그대로.
예: openrouter 의 "qwen/qwen3-32b", anthropic 의 "claude-sonnet-5".

형식이 어긋난 응답은 오류를 되돌려 한 번 더 묻고, 그래도 안 되면 LlmUnavailable.
시간 예산은 refine 그래프(l3_judge)가 밖에서 건다.
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import litellm

from contracts.engine_contract import JudgeDecision, JudgePrompt
from engine.errors import LlmUnavailable, log
from engine.tiers.l3 import tools


def register(model: str, provider: str | None, mode: str) -> str:
    """LiteLLM 표기(provider/model)를 만들고 레지스트리에 알린다.

    OpenRouter 는 LiteLLM 레지스트리에 없는 모델도 서빙한다. 미등록 모델은 요청 준비 단계
    (supports_reasoning 등)에서 provider 를 못 찾아 "Provider List" 안내를 stdout 에 찍으므로
    provider 와 mode 를 등록해 이름이 풀리게 한다. 이미 등록돼 있으면 건드리지 않는다.
    """
    full = f"{provider}/{model}" if provider else model
    if full not in litellm.model_cost:
        litellm.register_model({full: {"litellm_provider": provider or "", "mode": mode}})
    return full


class LiteLlmJudge:
    def __init__(
        self,
        model: str,
        *,
        provider: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
        max_retries: int = 1,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model = register(model, provider, "chat")
        self.extra_body = extra_body  # provider 전용 옵션 (예: OpenRouter reasoning 끄기)
        self.api_key = api_key
        self.api_base = api_base
        self.temperature = temperature
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    def decide(self, prompt: JudgePrompt) -> JudgeDecision:
        tool = tools.judge_tool(prompt)
        schema = tool["function"]["parameters"]
        messages: list[dict[str, Any]] = tools.messages(prompt)
        last: Exception | None = None
        for attempt in range(1 + self.max_retries):
            try:
                resp = litellm.completion(
                    model=self.model,
                    messages=messages,
                    tools=[tool],
                    tool_choice={"type": "function", "function": {"name": tools.TOOL_NAME}},
                    temperature=self.temperature,
                    timeout=self.timeout_s,
                    api_key=self.api_key,
                    api_base=self.api_base,
                    num_retries=0,
                    extra_body=self.extra_body,
                )
            except Exception as e:  # litellm 예외 계층이 넓다. 경계에서만 통째로 받는다
                raise LlmUnavailable(f"{self.model}: {type(e).__name__}: {e}") from e
            message = resp.choices[0].message
            tokens = getattr(getattr(resp, "usage", None), "total_tokens", None)
            try:
                args = _tool_args(message)
                jsonschema.validate(instance=args, schema=schema)
                return tools.to_decision(args, tokens)
            except (ValueError, jsonschema.ValidationError) as e:
                last = e
                log.warning("L3 응답 형식 오류 (시도 %d): %s", attempt + 1, e)
                messages = [
                    *messages,
                    {"role": "assistant", "content": message.content or ""},
                    {
                        "role": "user",
                        "content": (
                            f"형식 오류: {e}. `{tools.TOOL_NAME}` 툴을 스키마대로 다시 호출하라."
                        ),
                    },
                ]
        raise LlmUnavailable(f"{self.model}: 형식 오류 재시도 소진: {last}")


def _tool_args(message: Any) -> dict[str, Any]:
    calls = getattr(message, "tool_calls", None) or ()
    for call in calls:
        if call.function.name == tools.TOOL_NAME:
            try:
                args = json.loads(call.function.arguments)
            except json.JSONDecodeError as e:
                raise ValueError(f"툴 인자가 JSON 이 아님: {e}") from e
            if not isinstance(args, dict):
                raise ValueError("툴 인자 최상위가 객체가 아님")
            return args
    raise ValueError(f"`{tools.TOOL_NAME}` 툴 호출이 없음")
