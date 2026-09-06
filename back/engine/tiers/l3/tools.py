"""L3 툴 스키마와 메시지. JudgePrompt(구조) → 모델에 보낼 messages 와 tool 정의.

item_code·stated_elements 는 후보에서 만든 enum 이라 팩에 없는 코드를 구조로 막는다 (DESIGN 6.6).
evidence 는 모델이 쓰지 않는다. decision_parser 가 팩에서 붙인다 (P4).

툴 인자는 생성 순서가 판정 순서다: utterance_topic(발화 주제 한 구절) → topic_relations(후보마다
주제와의 관계) → verdicts(말한 요소만). Qwen3-8B 는 산문 규칙만으로는 주제가 다른 발화(연체이자 →
기한이익상실)를 걸러내지 못했고, 주제·관계를 먼저 쓰게 한 구조와 후보 밖 항목 이름(other_items)이
있어야 걸러냈다. 발화는 본문 마지막에 둔다(문맥 문장을 근거로 세는 일이 줄었다).
required/omission 의 상태는 모델의 state 가 아니라 stated_elements 로 계산한다.
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

PROMPT_VERSION = "2026-09-07.topic-relations"
"""판정 정책(프롬프트·스키마)이 바뀔 때 올린다. cache_key 에 들어가 옛 응답 재사용을 막는다."""

SYSTEM_PROMPT = """당신은 은행 창구 상담의 설명의무 이행을 심판하는 역할이다.
발화 하나와 후보 항목 몇 개를 받고, 그 발화가 각 항목의 상태를 어떻게 바꾸는지 판정한다.
반드시 `judge` 툴을 호출해서 답한다. 툴 밖의 문장은 무시된다.
speaker 가 teller 면 은행원, customer 면 고객의 발화다.
최근 문맥 앞의 [은행원]·[고객] 도 화자 표시다. 판정 대상은 본문 마지막의 utterance 하나다.

판정 순서 (툴 인자 순서와 같다)
1. utterance_topic: 이 발화가 무엇을 설명하는지 한 구절로 적는다.
2. topic_relations: 후보 항목마다 그 주제와 항목 이름의 관계를 정한다. 후보는 검색으로 뽑힌 것이라
   발화와 무관할 수 있다. 조건·결과·금액이 겹치더라도 실제 주제가 다른 사안(other_items 에 있는
   항목이거나 후보에 없는 사안)이면 other_topic 이다. 문맥만 그 사안이고 이 발화 자체는 설명하지
   않으면 explains_item 이 아니다. 한 발화가 여러 항목을 설명할 수 있고 항목마다 독립적으로 정한다.
3. verdicts: explains_item 인 항목만 넣는다. 요건 요소(requirement_elements)를 하나씩 이 발화의 어느
   문구가 말했는지 따져 실제로 말한 요소만 stated_elements 에 넣는다. 요소는 단어가 그대로 나오지
   않아도 그 취지가 담겨 있으면 말한 것이다 (예: "중도해지하면 이자가 줄어든다" 는 "만기 전 해지 시
   불이익" 을 말한 것이고, 계산 방법을 말로 풀어 설명한 것은 산출식·기준 류의 요소를 말한 것이다).
   "A 또는 B" 형태의 요소는 둘 중 하나만 언급해도 되고, 구체 수치까지는 요구하지 않는다.
   한 문구는 그 취지에 맞는 요소 하나만 말한 것으로 본다. 발화에 없는 내용을 짐작으로 채우지 않는다.
   current_states 의 missing_elements 는 이전 발화까지 채우지 못한 요소다. 이번 발화만 보고 적으면
   되고 이전에 채운 요소는 엔진이 합친다.

규칙
- 후보 항목만 판정한다. 발화가 건드리지 않은 항목은 verdicts 에 넣지 않는다.
- 은행원(teller) 발화:
  - required 항목 → axis=omission. 요소를 전부 말했으면 met, 일부만이면 partial.
    unmet 은 내지 않는다. 이미 met 인 항목은 되돌리지 않는다.
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
    names = " / ".join(f"{it.code}={it.name}" for it in prompt.candidate_items)
    relation = {
        "type": "object",
        "properties": {
            "item_code": {"type": "string", "enum": codes},
            "relation": {
                "type": "string",
                "enum": ["explains_item", "other_topic", "unrelated"],
                "description": (
                    "explains_item: 발화가 그 항목 이름의 사안 자체(그 사안이 생기는 경우나 "
                    "그 사안의 내용)를 설명한다. other_topic: 조건·결과·금액이 겹치더라도 "
                    "실제 주제는 다른 사안이다(other_items 에 있는 사안이면 other_topic). "
                    "unrelated: 무관하다"
                ),
            },
        },
        "required": ["item_code", "relation"],
        "additionalProperties": False,
    }
    verdict = {
        "type": "object",
        "properties": {
            "item_code": {"type": "string", "enum": codes},
            "stated_elements": {
                "type": "array",
                "items": {"type": "string", "enum": elements or ["(none)"]},
                "description": "이 발화가 실제로 말한 요건 요소만",
            },
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
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["item_code", "stated_elements", "axis", "state"],
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
                    "utterance_topic": {
                        "type": "string",
                        "description": (
                            "이 발화가 무엇을 설명하는지 한 구절로. 후보 이름과 같지 않아도 된다"
                        ),
                    },
                    "topic_relations": {
                        "type": "array",
                        "items": relation,
                        "description": (
                            f"후보 항목마다 하나씩. utterance_topic 과 항목 이름({names})의 관계"
                        ),
                    },
                    "verdicts": {"type": "array", "items": verdict},
                    "alerts": {"type": "array", "items": alert},
                },
                "required": ["utterance_topic", "topic_relations", "verdicts"],
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
        "recent_context": list(prompt.recent_context),
        "customer_type": prompt.customer_type,
        "candidate_items": items,
        "current_states": states,
        "other_items": list(prompt.other_item_names),
        "utterance": prompt.utterance_text,  # 판정 대상. 마지막에 두어 문맥과 섞이지 않게
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False, indent=1)},
    ]


def to_decision(args: dict[str, Any], tokens: int | None, prompt: JudgePrompt) -> JudgeDecision:
    """스키마 검증이 끝난 툴 인자 → JudgeDecision. 규칙 검사는 decision_parser 가 한다.

    topic_relations 가 explains_item 이 아닌 항목의 verdict 는 버린다(주제가 다른 발화).
    required 항목의 omission 은 stated_elements 로 state·missing_elements 를 계산한다.
    """
    relations = {r["item_code"]: r["relation"] for r in args.get("topic_relations", ())}
    items = {it.code: it for it in prompt.candidate_items}
    verdicts = []
    for v in args.get("verdicts", ()):
        if relations.get(v["item_code"], "explains_item") != "explains_item":
            continue
        item = items.get(v["item_code"])
        state, missing = v["state"], ()
        if v["axis"] == "omission" and item is not None and item.type == "required":
            stated = set(v.get("stated_elements", ()))
            missing = tuple(e for e in item.requirement_elements if e not in stated)
            state = "partial" if missing else "met"
        verdicts.append(
            VerdictPayload(
                item_code=v["item_code"],
                axis=v["axis"],
                state=state,
                decided_by="L3",
                confidence=v.get("confidence"),
                missing_elements=missing,
            )
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
    return JudgeDecision(verdicts=tuple(verdicts), alerts=alerts, tokens=tokens)
