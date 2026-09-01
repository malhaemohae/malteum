"""⑤ 숫자 대조. 발화의 수치를 팩 numeric_facts 와 비교해 불일치면 경보.

어느 단계에서도 숫자를 고치지 않는다. 이 발화가 건드린 항목(L1 히트)의 사실만 본다.
항목이 안 잡히면 대조하지 않는다 (오탐이 경보 무시를 부른다).
"""

from __future__ import annotations

import re

from contracts.engine_contract import AlertPayload, Comparison, PackItem
from engine.pack.compiler import CompiledPack, NumericRef

_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(%|퍼센트|프로|회|개월|만원|원|일|년)")
_UNIT = {"퍼센트": "%", "프로": "%"}


def said_numbers(text: str) -> list[tuple[float, str, str]]:
    """(값, 단위, 원문) 목록."""
    out = []
    for m in _NUMBER.finditer(text):
        unit = _UNIT.get(m.group(2), m.group(2))
        out.append((float(m.group(1)), unit, f"{m.group(1)}{unit}"))
    return out


def check(
    text: str, items: list[PackItem], compiled: CompiledPack, utterance_ref: str
) -> list[AlertPayload]:
    numbers = said_numbers(text)
    if not numbers:
        return []
    alerts: list[AlertPayload] = []
    for item in items:
        refs = compiled.numeric.get(item.code, ())
        for value, unit, raw in numbers:
            same_unit = [r for r in refs if r.fact.unit == unit]
            if not same_unit:
                continue
            if any(abs(float(r.fact.value) - value) <= r.fact.tolerance for r in same_unit):
                continue
            ref = next(
                (r for r in same_unit if r.fact.condition and r.fact.condition in text),
                same_unit[0],
            )
            alerts.append(
                AlertPayload(
                    alert_type="number_mismatch",
                    severity="warning",
                    message=f"설명서 기준 {_reference(ref)}"
                    + (f" ({ref.fact.condition})" if ref.fact.condition else ""),
                    item_code=item.code,
                    comparison=Comparison(
                        said=raw, reference=_reference(ref), condition=ref.fact.condition
                    ),
                    utterance_ref=utterance_ref,
                    evidence=ref.evidence or item.evidence,
                )
            )
    return alerts


def _reference(ref: NumericRef) -> str:
    if ref.evidence:
        m = re.search(r"(?:연\s*)?\d+(?:\.\d+)?\s*" + re.escape(ref.fact.unit), ref.evidence.span)
        if m:
            return re.sub(r"\s+", " ", m.group()).strip()
    return f"{ref.fact.value}{ref.fact.unit}"
