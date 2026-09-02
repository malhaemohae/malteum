"""RulePack + 원본 dict → CompiledPack.

계약 타입이 잃어버리는 정보(패턴↔요건 요소, 수치 근거)를 여기 둔다.
l1_patterns 가 비어 있으면 requirement_elements 로 임시 패턴을 만들고 시끄럽게 경고한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from contracts.engine_contract import Evidence, NumericFact
from engine.errors import warn_dummy
from engine.tiers.l0_normalize import JargonIndex
from engine.tiers.l2 import lexical
from engine.types import RulePack

DEFAULT_REASK_PATTERNS = (
    r"^\s*네\s*\?",
    r"(뭐|무슨|무엇)(예요|이에요|인가요|이죠|죠)",
    r"다시\s*(한\s*번|설명)",
    r"못\s*받아요\s*\?",
    r"그게\s*(뭐|무슨)",
    r"이해가\s*(안|잘)",
    r"\?\s*$",
)


@dataclass(frozen=True, slots=True)
class Pattern:
    kind: str
    regex: re.Pattern[str]
    element: str | None
    raw: str


@dataclass(frozen=True, slots=True)
class NumericRef:
    fact: NumericFact
    evidence: Evidence | None


@dataclass(frozen=True, slots=True)
class CompiledPack:
    pack_version: str
    patterns: dict[str, tuple[Pattern, ...]]
    numeric: dict[str, tuple[NumericRef, ...]]
    jargon: JargonIndex
    reask: tuple[re.Pattern[str], ...]
    jargon_terms: tuple[str, ...] = ()
    """⑧ 용어 밀도 게이지가 세는 목록. `jargon` 인덱스(항목명·요건 요소 포함)보다 좁다."""
    tri: lexical.TrigramIndex = field(default_factory=lambda: lexical.build({}))
    dummy_pattern_items: tuple[str, ...] = field(default=())


def compile_pack(raw: dict[str, Any], pack: RulePack) -> CompiledPack:
    patterns: dict[str, tuple[Pattern, ...]] = {}
    numeric: dict[str, tuple[NumericRef, ...]] = {}
    dummy: list[str] = []
    terms: list[str] = list(raw.get("jargon_terms", []))
    for it in raw["items"]:
        code = it["code"]
        terms.append(it["name"])
        terms.extend(it.get("requirement_elements", []))
        pats = [_compile(p) for p in it.get("l1_patterns", [])]
        if not pats and it["type"] in ("required", "forbidden", "risk"):
            pats = _dummy_patterns(it)
            if pats:
                dummy.append(code)
        patterns[code] = tuple(pats)
        numeric[code] = tuple(
            NumericRef(
                fact=NumericFact(
                    label=n["label"],
                    value=n["value"],
                    unit=n["unit"],
                    condition=n.get("condition"),
                    tolerance=n.get("tolerance", 0.0),
                ),
                evidence=_evidence(n.get("evidence")),
            )
            for n in it.get("numeric_facts", [])
        )
    if dummy:
        warn_dummy(
            f"l1_patterns 비어 있음 → requirement_elements 로 임시 keyword 패턴 생성: {dummy}"
        )
    reask_raw = raw.get("reask_patterns")
    if not reask_raw:
        reask_raw = DEFAULT_REASK_PATTERNS
        warn_dummy("팩에 reask_patterns 없음 → engine 기본 되물음 패턴 사용")
    # 주제 면(이름·요건·쉬운 말)과 예시 면(금지·위험 예시)을 문서로 분리하되 같은
    # 인덱스에 둔다. idf 통계는 주제 문서만으로 계산해, 예시 추가가 주제 점수를
    # 흔들지 않게 한다 (lexical.EXAMPLES_SUFFIX · build 의 stats 설명 참조)
    tri_texts = {
        it["code"]: lexical.item_text(
            it["name"],
            tuple(it.get("requirement_elements") or ()),
            tuple(it.get("plain_language") or ()),
        )
        for it in raw["items"]
        if it["type"] != "reference"
    }
    topic_keys = frozenset(tri_texts)
    for it in raw["items"]:
        examples = (*it.get("forbidden_examples", ()), *it.get("risk_examples", ()))
        if it["type"] in ("forbidden", "risk"):
            # 예시 문장 하나가 문서 하나다. 한 항목의 예시를 한 덩어리로 합치면
            # 발화가 여러 예시에서 조각을 조금씩 모아 임계를 넘는다 (2026-09-02
            # 실측: "중도해지하시면 0.5% 정도는 받으세요"가 단정 금지로 오탐)
            for i, example in enumerate(examples):
                tri_texts[f"{it['code']}{lexical.EXAMPLES_SUFFIX}{i}"] = example
    return CompiledPack(
        pack_version=pack.pack_version,
        patterns=patterns,
        numeric=numeric,
        jargon=JargonIndex(terms),
        jargon_terms=tuple(raw.get("jargon_terms", [])),
        reask=tuple(re.compile(r) for r in reask_raw),
        tri=lexical.build(tri_texts, stats=topic_keys),
        dummy_pattern_items=tuple(dummy),
    )


def _compile(p: dict[str, Any]) -> Pattern:
    kind, value = p["kind"], p["value"]
    flags = re.IGNORECASE if "i" in p.get("flags", "") else 0
    if kind == "keyword":
        rx = re.compile(re.escape(value), flags)
    elif kind == "regex":
        rx = re.compile(value, flags)
    elif kind == "numeric":
        rx = re.compile(r"(?<![\d.])" + re.escape(value) + r"(?![\d])")
    else:
        raise ValueError(f"알 수 없는 l1 패턴 kind: {kind}")
    return Pattern(kind=kind, regex=rx, element=p.get("element"), raw=value)


def _dummy_patterns(it: dict[str, Any]) -> list[Pattern]:
    if it["type"] == "forbidden":
        source = it.get("forbidden_examples", [])
    elif it["type"] == "risk":
        source = it.get("risk_examples", [])
    else:
        source = it.get("requirement_elements", [])
    out = []
    for text in source:
        element = text if it["type"] == "required" else None
        out.append(
            Pattern(kind="keyword", regex=re.compile(re.escape(text)), element=element, raw=text)
        )
    return out


def _evidence(e: dict[str, Any] | None) -> Evidence | None:
    if not e:
        return None
    bbox = e.get("bbox")
    return Evidence(
        doc_id=e["doc_id"],
        page=e["page"],
        span=e["span"],
        bbox=tuple(bbox) if bbox else None,
        legal_basis=e.get("legal_basis"),
    )
