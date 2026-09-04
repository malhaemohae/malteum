"""L0 정규화: 팩 용어 사전으로 STT 오인식을 치환한다. 숫자 토큰은 건드리지 않는다.

"차감율" → "차감률", "우대 이자 율" → "우대이자율". 후보가 유일하고 임계값 이상일 때만 바꾼다.
조사는 어절 끝에서 최대 두 글자까지 떼어 보고, 치환 뒤에 다시 붙인다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engine.tiers.jamo import dice, jamo_edit_distance, jamo_trigrams

DICE_THRESHOLD = 0.7
_HANGUL = re.compile(r"[가-힣]+")
_NUMERIC_NEAR = re.compile(r"\d")


@dataclass(frozen=True, slots=True)
class Replacement:
    original: str
    replaced: str
    score: float


class JargonIndex:
    def __init__(self, terms: list[str]) -> None:
        # 띄어쓰기 없는 용어만. 여러 어절짜리(요건 요소 등)는 L0 치환 대상이 아니라 검색 후보다
        self.terms = sorted(
            {t for t in terms if t and len(t) >= 2 and " " not in t}, key=len, reverse=True
        )
        self._grams = {t: jamo_trigrams(t) for t in self.terms}

    def candidates(self, token: str, top_k: int = 3) -> list[tuple[str, float]]:
        grams = jamo_trigrams(token)
        scored = [(t, dice(grams, g)) for t, g in self._grams.items()]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(t, s) for t, s in scored[:top_k] if s > 0]


def normalize(
    text: str, index: JargonIndex, threshold: float = DICE_THRESHOLD
) -> tuple[str, list[Replacement]]:
    if not index.terms:
        return text, []
    words = [(m.start(), m.end(), m.group()) for m in _HANGUL.finditer(text)]
    edits: list[tuple[int, int, str]] = []
    replacements: list[Replacement] = []
    i = 0
    while i < len(words):
        best: tuple[str, float, int, int] | None = None  # term, score, span, end
        settled = False
        for span in (3, 2, 1):
            if i + span > len(words):
                continue
            # 어절 사이에 공백만 있어야 붙여 본다
            if any(text[words[j][1] : words[j + 1][0]].strip() for j in range(i, i + span - 1)):
                continue
            end = words[i + span - 1][1]
            joined = "".join(w for _, _, w in words[i : i + span])
            for strip in (0, 1, 2):
                stem = joined[: len(joined) - strip] if strip else joined
                if len(stem) < 2:
                    continue
                if stem in index.terms:
                    # 이미 맞는 용어. 띄어쓰기만 다르면(span>1) 붙이고, 아니면 손대지 않는다
                    best = (stem, 1.0, span, end - strip) if span > 1 else None
                    settled = True
                    break
                if span > 1:
                    # 여러 어절을 붙이는 것은 정확 일치일 때만. 퍼지 결합은 앞 어절을
                    # 삼킨다 ("아까 중도해지 이자는" → "중도해지이율자는" 류의 과교정)
                    continue
                if any(t in stem for t in index.terms):
                    continue  # 맞는 용어를 이미 품고 있는 어절은 고치지 않는다
                cands = index.candidates(stem, top_k=2)
                if not cands:
                    continue
                term, score = cands[0]
                if term.startswith(stem) and len(term) > len(stem):
                    continue  # 말하지 않은 부분을 덧붙이는 치환은 하지 않는다
                unique = len(cands) == 1 or cands[1][1] < score
                close = (
                    len(stem) >= 3
                    and len(term) == len(stem)
                    and jamo_edit_distance(stem, term) <= 1
                )
                if (score >= threshold or close) and unique and (best is None or score > best[1]):
                    best = (term, score, span, end - strip)
            if settled:
                break
        if best is None:
            i += 1
            continue
        term, score, span, end = best
        start = words[i][0]
        original = text[start:end]
        if original != term:
            edits.append((start, end, term))
            replacements.append(Replacement(original, term, round(score, 3)))
        i += span
    if not edits:
        return text, []
    out, cursor = [], 0
    for start, end, term in edits:
        out.append(text[cursor:start])
        out.append(term)
        cursor = end
    out.append(text[cursor:])
    return "".join(out), replacements
