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


def build(texts: dict[str, str], *, stats: frozenset[str] | None = None) -> TrigramIndex:
    """`stats` 에 든 문서만 df·idf 계산에 참여한다. 기본은 전부.

    예시 가상 문서(`EXAMPLES_SUFFIX`)는 채점 대상이되 통계에는 안 넣는다.
    통계에 넣으면 예시 어휘가 주제 문서의 idf 를 깎아, 예시를 추가하는 것만으로
    기존 주제 점수가 흔들린다 (2026-09-02 실측: answer 임계 미달 회귀).
    통계 밖 문서에만 있는 trigram 은 idf 가 없어 채점에서 0 으로 친다.
    """
    grams = {code: frozenset(jamo_trigrams(t)) for code, t in texts.items()}
    stat_keys = stats if stats is not None else frozenset(grams)
    n = max(len(stat_keys), 1)
    df: dict[str, int] = {}
    for code in stat_keys:
        for t in grams.get(code, ()):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
    return TrigramIndex(grams=grams, idf=idf)


# 실측(6절 프로브): 관련 발화의 덮은 질량 6.6~31.7 · 무관 발화 ≤5.0
MIN_MATCH_IDF = 5.5
# 실측(L2 골든셋, 2026-09-02): trigram 이 신호를 이끄는 관련 발화는 겹침 7~24개,
# 무관 발화는 ≤6개. 문서가 몇 개 안 돼 idf 로는 어미 조각("있어요" 류)을 못 걸러서
# — 한 문서에만 나오면 어미도 idf 가 높다 — 질량과 별도로 개수 최소선을 둔다
MIN_MATCH_COUNT = 7


def coverage(text: str, index: TrigramIndex) -> dict[str, float]:
    """항목별 덮임 비율 (0~1). 절대 질량·개수 최소선 미달은 0."""
    qg = jamo_trigrams(text)
    denom = sum(index.idf.get(t, 0.0) for t in qg)
    if denom <= 0:
        return dict.fromkeys(index.grams, 0.0)
    out: dict[str, float] = {}
    for code, dg in index.grams.items():
        hit = qg & dg
        matched = sum(index.idf.get(t, 0.0) for t in hit)
        ok = matched >= MIN_MATCH_IDF and len(hit) >= MIN_MATCH_COUNT
        out[code] = matched / denom if ok else 0.0
    return out


def item_text(name: str, *parts_groups: tuple[str, ...]) -> str:
    return " ".join([name, *(p for g in parts_groups for p in g)])


# 금지·위험 예시를 주제 문서와 같은 인덱스 안의 가상 문서로 둘 때의 키 접미사.
# 예시를 주제 문서에 합치면 예시 어휘("중간에 해지하셔도 손해 없습니다")가 항목
# 주제로 흡수되어 정상 질문이 금지 항목으로 밀리고, 아예 다른 인덱스로 떼면
# 문서가 두어 개뿐이라 idf 분모가 무너진다 (2026-09-02 실측, 두 방향 모두)
EXAMPLES_SUFFIX = "#examples"
