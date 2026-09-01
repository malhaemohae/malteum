"""자모 trigram 덮임 점수. 임베딩과 병렬로 항목을 채점하는 문자 기반 신호 (착수 계획 6절).

점수 = 항목이 덮는 idf 질량 / 발화 중 사전에 있는 trigram 의 idf 질량 (0~1).
원점수는 발화 길이에 비례해 질의 간 비교가 안 되므로 질의 기준으로 정규화한다.
단 덮은 절대 질량이 MIN_MATCH_IDF 미만이면 0 — 팩과 무관한 발화("주차장 있어요?")는
우연히 겹친 조각 몇 개의 비율이 높게 나올 수 있어 절대 최소선으로 자른다.

실측(2026-09-01, 로컬 e5-small 대조): 짧은 구어 발화에서 dense 는 top-1 0/4 에
무관 발화 분리 불가, trigram 은 3/4 에 관련·무관이 갈렸다. 그래서 trigram 이 주 신호다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engine.tiers.jamo import jamo_trigrams


@dataclass(frozen=True, slots=True)
class TrigramIndex:
    grams: dict[str, frozenset[str]]  # item_code → 자모 trigram
    idf: dict[str, float]


def build(texts: dict[str, str]) -> TrigramIndex:
    grams = {code: frozenset(jamo_trigrams(t)) for code, t in texts.items()}
    n = max(len(grams), 1)
    df: dict[str, int] = {}
    for g in grams.values():
        for t in g:
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
    return TrigramIndex(grams=grams, idf=idf)


# 실측(6절 프로브): 관련 발화의 덮은 질량 6.6~31.7 · 무관 발화 ≤5.0
MIN_MATCH_IDF = 5.5


def coverage(text: str, index: TrigramIndex) -> dict[str, float]:
    """항목별 덮임 비율 (0~1). 절대 질량 최소선 미달은 0."""
    qg = jamo_trigrams(text)
    denom = sum(index.idf.get(t, 0.0) for t in qg)
    if denom <= 0:
        return dict.fromkeys(index.grams, 0.0)
    out: dict[str, float] = {}
    for code, dg in index.grams.items():
        matched = sum(index.idf.get(t, 0.0) for t in qg & dg)
        out[code] = matched / denom if matched >= MIN_MATCH_IDF else 0.0
    return out


def item_text(name: str, *parts_groups: tuple[str, ...]) -> str:
    return " ".join([name, *(p for g in parts_groups for p in g)])
