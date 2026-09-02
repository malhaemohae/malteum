"""실물 LLM 어댑터 (LiteLLM). 심판(LiteLlmJudge)·교정(LiteLlmCorrector)·생성(LiteLlmGenerator).

model 은 provider 공식 표기 그대로.
예: openrouter 의 "qwen/qwen3-32b", anthropic 의 "claude-sonnet-5".

심판은 tool calling 을 강제하고, 형식이 어긋난 응답은 오류를 되돌려 한 번 더 묻고,
그래도 안 되면 LlmUnavailable. 시간 예산은 refine 그래프(l3_judge)가 밖에서 건다.
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
        litellm.register_model(
            {
                full: {
                    "litellm_provider": provider or "",
                    "mode": mode,
                    # 등록 안 하면 LiteLLM 이 경고를 찍는다. 단가는 모르는 것이므로 0
                    "cache_creation_input_token_cost": 0.0,
                    "cache_read_input_token_cost": 0.0,
                }
            }
        )
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
        transport_retries: int = 2,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model = register(model, provider, "chat")
        self.extra_body = extra_body  # provider 전용 옵션 (예: OpenRouter reasoning 끄기)
        self.api_key = api_key
        self.api_base = api_base
        self.temperature = temperature
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.transport_retries = transport_retries  # 429·일시 오류는 litellm 백오프로

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
                    num_retries=self.transport_retries,
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


_CORRECT_PROMPT = """은행 창구 발화의 음성 전사(STT) 교정을 돕는다.
발화의 어절 하나가 금융 용어를 잘못 받아 적은 것인지 판단해 `propose` 툴로 답한다.
후보 목록에 있는 (어절, 용어) 짝 중에서만 고른다. 발음이 비슷하고 문맥상 그 용어가
분명할 때만 제안하고, 확신이 없으면 빈 목록을 낸다. 숫자는 절대 바꾸지 않는다."""


class LiteLlmCorrector:
    """refine 그래프 correct 노드용. 실패하면 빈 목록(교정 포기, 원문 유지)."""

    def __init__(
        self,
        model: str,
        *,
        provider: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout_s: float = 10.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model = register(model, provider, "chat")
        self.api_key = api_key
        self.api_base = api_base
        self.timeout_s = timeout_s
        self.extra_body = extra_body

    def correct(self, text: str, candidates: list[tuple[str, str, float]]) -> list[tuple[str, str]]:
        tool = {
            "type": "function",
            "function": {
                "name": "propose",
                "description": "잘못 전사된 어절 → 올바른 용어 교정 제안",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "corrections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "word": {
                                        "type": "string",
                                        "enum": [w for w, _, _ in candidates],
                                    },
                                    "term": {
                                        "type": "string",
                                        "enum": [t for _, t, _ in candidates],
                                    },
                                },
                                "required": ["word", "term"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["corrections"],
                    "additionalProperties": False,
                },
            },
        }
        body = {"utterance": text, "candidates": [{"word": w, "term": t} for w, t, _ in candidates]}
        try:
            resp = litellm.completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": _CORRECT_PROMPT},
                    {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
                ],
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": "propose"}},
                temperature=0.0,
                timeout=self.timeout_s,
                api_key=self.api_key,
                api_base=self.api_base,
                num_retries=1,
                extra_body=self.extra_body,
            )
            calls = resp.choices[0].message.tool_calls or ()
            args = json.loads(calls[0].function.arguments) if calls else {}
            picks = args.get("corrections", ())
            return [(c["word"], c["term"]) for c in picks if isinstance(c, dict)]
        except Exception as e:  # 교정은 부가 기능. 어떤 실패든 원문 유지가 안전하다
            log.warning("교정 호출 실패 → 원문 유지: %s", e)
            return []


_GENERATE_PROMPT = """은행 창구 상담을 돕는 답변기다.
고객 질문에 아래 근거 문장만으로 한두 문장으로 답한다.
근거에 없는 내용·숫자를 새로 만들지 않는다. 근거 문장의 표현과 숫자를 그대로 쓴다.
근거로 답할 수 없는 질문이면 근거 문장 중 가장 가까운 것을 그대로 돌려준다."""


class LiteLlmGenerator:
    """assist 그래프 generate 노드용. 반환 문장은 guard(P4)가 근거와 대조해 걸러낸다."""

    def __init__(
        self,
        model: str,
        *,
        provider: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout_s: float = 10.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model = register(model, provider, "chat")
        self.api_key = api_key
        self.api_base = api_base
        self.timeout_s = timeout_s
        self.extra_body = extra_body

    def generate(self, question: str, evidence_texts: list[str]) -> str:
        body = {"question": question, "evidence": evidence_texts}
        try:
            resp = litellm.completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": _GENERATE_PROMPT},
                    {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
                ],
                temperature=0.0,
                timeout=self.timeout_s,
                api_key=self.api_key,
                api_base=self.api_base,
                num_retries=1,
                extra_body=self.extra_body,
            )
            text = resp.choices[0].message.content or ""
            return text.strip() or (evidence_texts[0] if evidence_texts else "")
        except Exception as e:  # 실패하면 근거 문장 그대로 (guard 는 통과한다)
            log.warning("생성 호출 실패 → 근거 문장 유지: %s", e)
            return evidence_texts[0] if evidence_texts else ""
