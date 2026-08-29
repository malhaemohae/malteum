"""테스트용 임베더. 문구 → 항목 코드 표로 결정적 벡터를 만든다. 표는 테스트 데이터다."""

from __future__ import annotations

import math
from collections.abc import Sequence


class FakeEmbedder:
    def __init__(
        self, codes: Sequence[str], phrases: dict[str, str] | None = None, dim: int = 384
    ) -> None:
        self.codes = list(codes)
        self.phrases = dict(phrases or {})
        self.dim = dim
        self.calls = 0

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for i, code in enumerate(self.codes):
                if code in text:
                    vec[i] += 1.0
            for phrase, code in self.phrases.items():
                if phrase in text:
                    vec[self.codes.index(code)] += 1.0
            norm = math.sqrt(sum(v * v for v in vec))
            out.append([v / norm for v in vec] if norm else vec)
        return out
