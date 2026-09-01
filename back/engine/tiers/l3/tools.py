"""L3 툴 스키마와 메시지. JudgePrompt(구조) → 모델에 보낼 messages 와 tool 정의.

item_code·missing_elements 는 후보에서 만든 enum 이라 팩에 없는 코드를 구조로 막는다 (DESIGN 6.6).
evidence 는 모델이 쓰지 않는다. decision_parser 가 팩에서 붙인다 (P4).
"""

from __future__ import annotations

import json
from typing import Any

from contracts.engine_contract import (
    AlertPayload,
    JudgeDecision,
    JudgePrompt,
    VerdictPayload,
)

TOOL_NAME = "judge"

SYSTEM_PROMPT = """당신은 은행 창구 상담의 설명의무 이행을 심판하는 역할이다.
발화 하나와 후보 항목 몇 개를 받고, 그 발화가 각 항목의 상태를 어떻게 바꾸는지 판정한다.
반드시 `judge` 툴을 호출해서 답한다. 툴 밖의 문장은 무시된다.
speaker 가 teller 면 은행원, customer 면 고객의 발화다.
최근 문맥 앞의 [은행원]·[고객] 도 화자 표시다.

규칙
- 후보 항목만 판정한다. 발화가 건드리지 않은 항목은 verdicts 에 넣지 않는다.
- 은행원(teller) 발화:
  - required 항목 → axis=omission. 요건 요소(requirement_elements)를 전부 충족하면 met,
    일부만이면 partial 과 함께 빠진 요소를 missing_elements 에 그대로 적는다.
    요소는 단어가 그대로 나오지 않아도 그 취지가 담겨 있으면 충족으로 본다
    (예: "중도해지하면 이자가 줄어든다" 는 "만기 전 해지 시 불이익" 을 충족하고,
    계산 방법을 말로 풀어 설명한 것은 산출식·기준 류의 요소를 충족한다).
    "A 또는 B" 형태의 요소는 둘 중 하나만 언급해도 충족이고, 구체 수치까지는
    요구하지 않는다 — 어떤 방식·기준으로 정해지는지를 말했으면 충족이다.
    판정 전에 요소 하나씩 발화의 어느 문구가 충족하는지 따져 보고,
    근거 문구를 찾지 못한 요소만 missing_elements 에 넣는다.
    unmet 은 내지 않는다. 항목을 전혀 건드리지 않았으면 verdicts 에서 뺀다.
    이미 met 인 항목은 되돌리지 않는다.
  - forbidden 항목 → axis=commission. 금지된 취지의 말을 실제로 했으면 violated,
    비슷하지만 금지 취지가 아니면 clean.
- 고객(customer) 발화:
  - axis=comprehension 만 낸다. 고객이 설명 내용을 스스로 옳게 되짚었으면 confirmed.
  - 고객 발화로 omission·commission 판정을 만들지 않는다.
- 숫자가 문서와 다른지는 다른 층이 검사한다. 여기서는 설명의 완결성과 취지만 본다.
- 확신이 없으면 verdicts 를 비운다. 억지로 판정하지 않는다.
- message 는 고객이 화면을 볼 수 있다는 전제로 쓴다. 은행원을 비난하는 문구를 쓰지 않는다."""


def judge_tool(prompt: JudgePrompt) -> dict[str, Any]:
    codes = [it.code for it in prompt.candidate_items] or ["(none)"]
    elements = sorted({e for it in prompt.candidate_items for e in it.requirement_elements})
    verdict = {
        "type": "object",
        "properties": {
            "item_code": {"type": "string", "enum": codes},
            "axis": {"type": "string", "enum": ["omission", "commission", "comprehension"]},
            "state": {
                "type": "string",
                "enum": [
                    "unmet",
                    "partial",
                    "met",
                    "clean",
                    "suspected",
                    "violated",
                    "explained",
                    "confirmed",
                ],
            },  # fmt: skip
            "missing_elements": {
                "type": "array",
                "items": {"type": "string", "enum": elements or ["(none)"]},
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["item_code", "axis", "state"],
        "additionalProperties": False,
    }
    alert = {
        "type": "object",
        "properties": {
            "alert_type": {"type": "string", "enum": ["forbidden_phrase", "risk_signal"]},
            "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
            "message": {"type": "string"},
            "item_code": {"type": "string", "enum": codes},
        },
        "required": ["alert_type", "severity", "message"],
        "additionalProperties": False,
    }
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "발화가 후보 항목의 상태를 어떻게 바꾸는지 판정한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdicts": {"type": "array", "items": verdict},
                    "alerts": {"type": "array", "items": alert},
                },
                "required": ["verdicts"],
                "additionalProperties": False,
            },
        },
    }


def messages(prompt: JudgePrompt) -> list[dict[str, str]]:
    items = [
        {
            "code": it.code,
            "name": it.name,
            "type": it.type,
            "requirement_elements": list(it.requirement_elements),
            "forbidden_examples": list(it.forbidden_examples),
            "plain_language": list(it.plain_language),
        }
        for it in prompt.candidate_items
    ]
    states = [
        {
            "item_code": s.item_code,
            "axis": s.axis,
            "state": s.state,
            "missing_elements": list(s.missing_elements),
        }
        for s in prompt.current_states
    ]
    body = {
        "speaker": prompt.speaker,
        "utterance": prompt.utterance_text,
        "recent_context": list(prompt.recent_context),
        "customer_type": prompt.customer_type,
        "candidate_items": items,
        "current_states": states,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False, indent=1)},
    ]


def to_decision(args: dict[str, Any], tokens: int | None) -> JudgeDecision:
    """스키마 검증이 끝난 툴 인자 → JudgeDecision. 규칙 검사는 decision_parser 가 한다."""
    verdicts = tuple(
        VerdictPayload(
            item_code=v["item_code"],
            axis=v["axis"],
            state=v["state"],
            decided_by="L3",
            confidence=v.get("confidence"),
            missing_elements=tuple(v.get("missing_elements", ())),
        )
        for v in args.get("verdicts", ())
    )
    alerts = tuple(
        AlertPayload(
            alert_type=a["alert_type"],
            severity=a["severity"],
            message=a["message"],
            item_code=a.get("item_code"),
        )
        for a in args.get("alerts", ())
    )
    return JudgeDecision(verdicts=verdicts, alerts=alerts, tokens=tokens)
