"""화자·신뢰도 게이트. 이 발화가 어느 타입의 항목을 건드릴 수 있는지 정한다.

required·forbidden 은 은행원 발화만, risk·comprehension 은 고객 발화만 본다.
`risk_speaker_fallback` 은 고객의 요청형 위험 발화가 은행원으로 잘못 분류된 경우를 찾는다.
은행원 발화의 화자 신뢰도가 낮으면 아무 항목도 올리지 않는다.
P3: 잘못된 met 가 잘못된 unmet 보다 위험하다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from contracts.engine_contract import Utterance

SPEAKER_CONFIDENCE_THRESHOLD = 0.6
_CUSTOMER_REQUEST = re.compile(
    r"주세요|(?:으)?려고요|[았었했]어요|하던데요|하라고\s*(했|하던|한대)|해야\s*한대"
)
_TELLER_GUIDANCE = re.compile(
    r"예를\s*들|확인해\s*드|(?:보내|입금|이체|설치|상환).{0,20}(?:마세요|안\s*됩니다)"
)


@dataclass(frozen=True, slots=True)
class Gate:
    types: frozenset[str]
    low_confidence: bool = False


def gate(utterance: Utterance, threshold: float = SPEAKER_CONFIDENCE_THRESHOLD) -> Gate:
    conf = utterance.speaker_confidence
    if utterance.speaker == "teller":
        if conf is not None and conf < threshold:
            return Gate(frozenset(), low_confidence=True)
        return Gate(frozenset({"required", "forbidden"}))
    if utterance.speaker == "customer":
        return Gate(frozenset({"risk", "comprehension"}))
    return Gate(frozenset())


def risk_speaker_fallback(utterance: Utterance) -> bool:
    return (
        utterance.speaker == "teller"
        and _CUSTOMER_REQUEST.search(utterance.text) is not None
        and _TELLER_GUIDANCE.search(utterance.text) is None
    )
