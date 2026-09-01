"""테스트용 어댑터. fixture 기대값을 그대로 돌려주는 결정적 구현이지 스텁이 아니다 (DESIGN 6.7).

PHRASES·SCRIPT 같은 표는 각 테스트가 넘기는 테스트 데이터다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from contracts.engine_contract import Chunk, Embedder, JudgeDecision, JudgePrompt
from engine.adapters.vector_index.memory import cosine
from engine.errors import warn_dummy
from engine.pack.source import PackNotFound


class FakePackSource:
    def __init__(self, *packs: dict[str, Any]) -> None:
        self.packs = {p["pack_version"]: p for p in packs}

    def read(self, pack_version: str) -> dict[str, Any]:
        try:
            return self.packs[pack_version]
        except KeyError:
            raise PackNotFound(pack_version) from None


class FakeEmbedder:
    """문구 → 항목 코드 표로 결정적 벡터를 만든다."""

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


class FakeChunkIndex:
    """청크 몇 개를 메모리에 두고 코사인으로 찾는다. 비어 있으면 경고."""

    def __init__(self, chunks: Sequence[Chunk], embedder: Embedder) -> None:
        self.chunks = list(chunks)
        self._vectors = embedder.encode([c.text for c in self.chunks]) if self.chunks else []
        if not self.chunks:
            warn_dummy("ChunkIndex 비어 있음 → 문서 본문 검색은 항상 근거 없음")

    def search(
        self, vector: Sequence[float], top_k: int, doc_ids: Sequence[str] | None = None
    ) -> list[tuple[Chunk, float]]:
        rows = [
            (c, cosine(vector, v))
            for c, v in zip(self.chunks, self._vectors, strict=True)
            if doc_ids is None or c.doc_id in doc_ids
        ]
        rows.sort(key=lambda x: x[1], reverse=True)
        return [(c, s) for c, s in rows[:top_k] if s > 0]


class ScriptedLlmJudge:
    """발화 텍스트 → JudgeDecision 스크립트. 없는 발화는 빈 결정(잠정 판정 유지)."""

    model = "fake-scripted"

    def __init__(self, script: dict[str, JudgeDecision] | None = None) -> None:
        self.script = dict(script or {})
        self.prompts: list[JudgePrompt] = []

    def decide(self, prompt: JudgePrompt) -> JudgeDecision:
        """정확히 같은 발화가 우선, 없으면 스크립트 키가 발화에 포함되는 것."""
        self.prompts.append(prompt)
        text = prompt.utterance_text
        if text in self.script:
            return self.script[text]
        for key, decision in self.script.items():
            if key in text:
                return decision
        return JudgeDecision()
