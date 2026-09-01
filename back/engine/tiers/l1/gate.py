"""화자·신뢰도 게이트. 이 발화가 어느 타입의 항목을 건드릴 수 있는지 정한다.

required·forbidden 은 은행원 발화만, risk·comprehension 은 고객 발화만 본다.
은행원 발화의 화자 신뢰도가 낮으면 아무 항목도 올리지 않는다.
P3: 잘못된 met 가 잘못된 unmet 보다 위험하다.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.engine_contract import Utterance

SPEAKER_CONFIDENCE_THRESHOLD = 0.6


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
