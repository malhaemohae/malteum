"""LLM 교정 툴에 넘길 후보 용어. L0 가 확신하지 못해 치환하지 않은 애매한 어절을 모은다."""

from __future__ import annotations

import re

from engine.tiers.l0_normalize import DICE_THRESHOLD, JargonIndex

LOW = 0.4
_HANGUL = re.compile(r"[가-힣]{2,}")


def candidates(text: str, index: JargonIndex, top_k: int = 5) -> list[tuple[str, str, float]]:
    """(발화 어절, 후보 용어, 점수). 이미 정확한 용어가 들어 있는 어절은 제외."""
    out: list[tuple[str, str, float]] = []
    for word in _HANGUL.findall(text):
        if any(t in word for t in index.terms):
            continue
        for strip in (0, 1, 2):
            stem = word[: len(word) - strip] if strip else word
            if len(stem) < 2:
                break
            for term, score in index.candidates(stem, top_k=2):
                if LOW <= score < DICE_THRESHOLD:
                    out.append((stem, term, round(score, 3)))
    out.sort(key=lambda x: x[2], reverse=True)
    seen: set[tuple[str, str]] = set()
    uniq = []
    for w, t, s in out:
        if (w, t) not in seen:
            seen.add((w, t))
            uniq.append((w, t, s))
    return uniq[:top_k]
