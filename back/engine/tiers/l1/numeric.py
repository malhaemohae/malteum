"""⑤ 숫자 대조. 발화의 수치를 팩 numeric_facts 와 비교해 불일치면 경보.

원문은 고치지 않는다. 수치 앞의 주제·팩의 label 로 비교 대상을 좁힌다.
숫자만 이어 말하면 가까운 직전 은행원 발화를 보고, 대상이 모호하면 대조하지 않는다.
"""

from __future__ import annotations

import re

from contracts.engine_contract import AlertPayload, Comparison, PackItem, Utterance
from engine.pack.compiler import CompiledPack, NumericRef
from engine.tiers.l0_normalize import normalize
from engine.tiers.l1 import matcher
from engine.tiers.l1.gate import gate
from engine.types import RulePack, SessionState

_PERCENT = r"(?:%|퍼센트|프로|퍼(?!센|포))(?!\s*(?:포인트|[pP]))"
_NUMBER = re.compile(
    r"(?<![\d.,])(?P<digits>[+-]?\d+(?:\.\d+)?)\s*"
    rf"(?P<unit>{_PERCENT}|회|개월|만원|원|일|년)"
    r"|(?<![가-힣\d.])(?P<korean>[\d영공일이삼사오육칠팔구십백천만억조점]+"
    r"(?:\s+[\d영공일이삼사오육칠팔구십백천만억조점]+)*)"
    rf"\s*(?P<kunit>{_PERCENT})"
)
_UNIT = {"퍼센트": "%", "프로": "%", "퍼": "%"}
_DIGITS = dict(zip("영일이삼사오육칠팔구", "0123456789", strict=True)) | {"공": "0"}
# ponytail: 한글 수사는 0~9999와 '점' 뒤 낱자리만 지원. 그 밖의 수사는 실측 사례로 확장한다.
_INTEGER = re.compile(
    r"(?:[일이삼사오육칠팔구]?천)?(?:[일이삼사오육칠팔구]?백)?"
    r"(?:[일이삼사오육칠팔구]?십)?[일이삼사오육칠팔구]?|[영공]"
)
# ponytail: 문맥은 직전 한 발화·종료 후 10초까지. 다중 턴 연결은 STT 실측 후 확장한다.
CONTEXT_GAP_MS = 10_000


def _number(m: re.Match[str]) -> tuple[float, str, str] | None:
    raw = m["digits"]
    unit = m["unit"]
    if raw is None:
        integer, point, decimal = re.sub(r"\s+", "", m["korean"]).partition("점")
        if not integer or not _INTEGER.fullmatch(integer):
            return None
        if point and (not decimal or any(c not in _DIGITS for c in decimal)):
            return None
        total = digit = 0
        for c in integer:
            if c in _DIGITS:
                digit = int(_DIGITS[c])
            else:
                total += (digit or 1) * {"십": 10, "백": 100, "천": 1000}[c]
                digit = 0
        raw = str(total + digit)
        if decimal:
            raw += "." + "".join(_DIGITS[c] for c in decimal)
        unit = m["kunit"]
    unit = _UNIT.get(unit, unit)
    return float(raw), unit, f"{raw}{unit}"


def said_numbers(text: str) -> list[tuple[float, str, str]]:
    """(값, 단위, 비교용 표기) 목록. 전사 원문은 변경하지 않는다."""
    return [number for m in _NUMBER.finditer(text) if (number := _number(m)) is not None]


def check(
    utterance: Utterance, pack: RulePack, compiled: CompiledPack, state: SessionState
) -> list[AlertPayload]:
    text = utterance.text
    alerts: list[AlertPayload] = []
    cursor = 0
    matches = list(_NUMBER.finditer(text))
    for m in matches:
        prefix = text[cursor : m.start()]
        cursor = m.end()
        number = _number(m)
        if number is None:
            continue
        value, unit, raw = number
        targets = _targets(prefix, unit, pack, compiled)
        if not targets and len(matches) == 1 and _continuation(prefix, "", ""):
            # '15일 이내에 청약철회'처럼 숫자를 먼저 말하는 문장도 대조한다.
            targets = _targets(text[m.end() :], unit, pack, compiled)
        if not targets and state.recent_utterances:
            previous = state.recent_utterances[-1]
            gap = utterance.t_ms - previous.t_ms - (previous.duration_ms or 0)
            if (
                previous.utterance_id != utterance.utterance_id
                and "required" in gate(previous).types
                and 0 <= gap <= CONTEXT_GAP_MS
            ):
                targets = [
                    (item, ref)
                    for item, ref in _targets(previous.text, unit, pack, compiled)
                    if _continuation(prefix, text[m.end() :], ref.fact.label)
                ]
        if len(targets) != 1:
            continue
        item, ref = targets[0]
        if abs(float(ref.fact.value) - value) <= ref.fact.tolerance:
            continue
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
                utterance_ref=utterance.utterance_id,
                evidence=ref.evidence or item.evidence,
            )
        )
    return alerts


def _targets(
    text: str, unit: str, pack: RulePack, compiled: CompiledPack
) -> list[tuple[PackItem, NumericRef]]:
    text, _ = normalize(text, compiled.jargon)
    joined = re.sub(r"\s+", "", text)
    hits = [h for h in matcher.match(text, pack, compiled, frozenset({"required"})) if h.topical]
    if len(hits) > 1:
        return []
    targets = []
    named = []
    for item in pack.required_items():
        hit = next((h for h in hits if h.item.code == item.code), None)
        for ref in compiled.numeric.get(item.code, ()):
            if ref.fact.unit != unit:
                continue
            # 약정금리와 연체가산금리는 같은 항목·단위여도 다른 수치다.
            if (
                hit is not None
                and ref.fact.label in item.requirement_elements
                and hit.elements != {ref.fact.label}
            ):
                continue
            label = re.sub(r"\s+", "", ref.fact.label)
            if label and label in joined:
                named.append((item, ref))
            elif hit is not None:
                targets.append((item, ref))
    targets = named or targets
    conditioned = [(it, r) for it, r in targets if r.fact.condition and r.fact.condition in text]
    return conditioned or targets


def _continuation(prefix: str, suffix: str, label: str) -> bool:
    """숫자만 또는 직전 수치 label 의 끝말('세율은')만 이어 말할 때 문맥을 빌린다."""
    if not re.fullmatch(
        r"\s*(?:정도)?\s*(?:입니다|예요|이에요|이고요|이고|됩니다)?[\s.!?]*", suffix
    ):
        return False
    prefix = re.sub(r"\s+", "", prefix)
    if prefix in ("", "연", "약", "연약"):
        return True
    subject = re.fullmatch(r"([가-힣]{2,}?)(?:은|는|이|가)?(?:연|약)?", prefix)
    return subject is not None and re.sub(r"\s+", "", label).endswith(subject[1])


def _reference(ref: NumericRef) -> str:
    if ref.evidence:
        m = re.search(r"(?:연\s*)?\d+(?:\.\d+)?\s*" + re.escape(ref.fact.unit), ref.evidence.span)
        if m:
            return re.sub(r"\s+", " ", m.group()).strip()
    return f"{ref.fact.value}{ref.fact.unit}"
