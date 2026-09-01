"""자모 NFD trigram. 짧은 문자열끼리의 유사도(Dice)에 쓴다. 표준 라이브러리만."""

from __future__ import annotations

import unicodedata


def jamo_trigrams(text: str) -> set[str]:
    jamo = unicodedata.normalize("NFD", text.lower().replace(" ", ""))
    if len(jamo) < 3:
        return {jamo} if jamo else set()
    return {jamo[i : i + 3] for i in range(len(jamo) - 2)}


def dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def jamo_edit_distance(a: str, b: str) -> int:
    """자모 단위 편집거리. 율/률처럼 자모 하나 차이인 짧은 단어를 Dice 가 놓칠 때 쓴다."""
    x = unicodedata.normalize("NFD", a.replace(" ", ""))
    y = unicodedata.normalize("NFD", b.replace(" ", ""))
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cx != cy)))
        prev = cur
    return prev[-1]
