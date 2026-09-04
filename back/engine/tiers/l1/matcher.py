"""L1 결정 규칙. 팩의 keyword·regex 패턴으로 요건 요소 충족을 본다. LLM 없음, 약 1ms."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.engine_contract import AlertPayload, ItemState, PackItem, VerdictPayload
from engine.pack.compiler import CompiledPack
from engine.types import RulePack


@dataclass(frozen=True, slots=True)
class Hit:
    item: PackItem
    elements: frozenset[str]  # 이 발화가 충족시킨 요건 요소 (required 만 의미 있음)
    patterns: tuple[str, ...]
    kinds: frozenset[str] = frozenset()

    def type_is(self, t: str) -> bool:
        return self.item.type == t

    @property
    def topical(self) -> bool:
        """숫자 패턴만 맞은 히트는 주제가 아니다. 0.10% 는 여러 항목에 같은 값으로 나온다."""
        return bool(self.kinds - {"numeric"})


def match(text: str, pack: RulePack, compiled: CompiledPack, types: frozenset[str]) -> list[Hit]:
    hits: list[Hit] = []
    # STT 는 복합어를 자주 띄운다("총 부채 원리금", "중도 해지 이율"). keyword 패턴(용어 하나를
    # 그대로 적은 것)은 공백을 뺀 본문에도 대 본다. regex 는 대상에서 뺀다 — 작성자가 \s* 로
    # 띄어쓰기 허용 여부를 이미 정했고, 공백을 지우면 "경과 기간에" 같은 어절 경계가 사라져
    # 다른 항목의 요소가 우연히 채워진다(시연 A10 에서 DEP-INT-002 가 잘못 met 이 됐다)
    joined = text.replace(" ", "")
    for item in pack.items:
        if item.type not in types:
            continue
        elements: set[str] = set()
        raws: list[str] = []
        kinds: set[str] = set()
        for p in compiled.patterns.get(item.code, ()):
            spaced = p.kind == "keyword" and joined != text
            if p.regex.search(text) or (spaced and p.regex.search(joined)):
                raws.append(p.raw)
                kinds.add(p.kind)
                if p.element:
                    elements.add(p.element)
        if raws:
            hits.append(
                Hit(
                    item=item,
                    elements=frozenset(elements),
                    patterns=tuple(raws),
                    kinds=frozenset(kinds),
                )
            )
    return hits


def required_verdict(
    hit: Hit, current: ItemState | None, utterance_ref: str, numeric_context: bool = False
) -> VerdictPayload | None:
    """요건 요소 충족으로 met/partial.

    요소 하나짜리 일반 키워드 히트는 주제 언급일 뿐이라 판정하지 않는다.

    예: "중도해지" 한 단어는 중도해지 이자율 항목을 설명한 증거가 아니다. 단 같은 발화에 그 항목의
    수치가 나오면(numeric_context) 설명 중인 것으로 보고 partial 로 올린다.
    """
    item = hit.item
    if current is not None and current.state in ("met", "waived"):
        return None
    elements = list(item.requirement_elements)
    known = (
        set(elements) - set(current.missing_elements)
        if current and current.state == "partial" and current.missing_elements
        else set()
    )
    satisfied = known | set(hit.elements)
    if not satisfied:
        return None
    missing = tuple(e for e in elements if e not in satisfied)
    if missing and len(hit.elements) < 2 and not numeric_context and not known:
        return None
    state = "met" if not missing else "partial"
    if (
        current is not None
        and current.state == state
        and tuple(current.missing_elements) == missing
    ):
        return None
    return VerdictPayload(
        item_code=item.code,
        axis="omission",
        state=state,
        decided_by="L1",
        missing_elements=missing,
        utterance_ref=utterance_ref,
        evidence=item.evidence,
    )


def forbidden_verdict(
    hit: Hit, current: ItemState | None, utterance_ref: str, decided_by: str = "L1"
) -> tuple[VerdictPayload | None, AlertPayload]:
    item = hit.item
    alert = AlertPayload(
        alert_type="forbidden_phrase",
        severity="warning",
        message=f"설명서 기준 확인이 필요합니다: {item.name}",
        item_code=item.code,
        utterance_ref=utterance_ref,
        evidence=item.evidence,
    )
    if current is not None and current.state == "violated":
        return None, alert
    verdict = VerdictPayload(
        item_code=item.code,
        axis="commission",
        state="suspected",
        decided_by=decided_by,
        utterance_ref=utterance_ref,
        evidence=item.evidence,
    )
    return verdict, alert


def risk_alert(hit: Hit, utterance_ref: str) -> AlertPayload:
    item = hit.item
    return AlertPayload(
        alert_type="risk_signal",
        severity="critical",
        message=f"위험 신호: {item.name}. 본인 의사와 거래 목적 확인이 필요합니다",
        item_code=item.code,
        utterance_ref=utterance_ref,
        evidence=item.evidence,
    )
