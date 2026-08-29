"""팩 항목 벡터를 메모리에 두는 VectorIndex. 항목이 수십 개라 MVP 는 이것으로 충분하다."""

from __future__ import annotations

import math
from collections.abc import Sequence

from contracts.engine_contract import Embedder, PackItem
from engine.types import RulePack


def item_text(it: PackItem) -> str:
    parts = [
        it.code,
        it.name,
        *it.requirement_elements,
        *it.forbidden_examples,
        *it.risk_examples,
        *it.plain_language,
    ]
    return " ".join(parts)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class MemoryVectorIndex:
    def __init__(self) -> None:
        self._packs: dict[str, list[tuple[str, list[float]]]] = {}

    def add_pack(self, pack: RulePack, embedder: Embedder) -> None:
        if pack.pack_version in self._packs:
            return
        items = [it for it in pack.items if it.type != "reference"]
        vectors = embedder.encode([item_text(it) for it in items])
        self._packs[pack.pack_version] = [
            (it.code, v) for it, v in zip(items, vectors, strict=True)
        ]

    def search(
        self, pack_version: str, vector: Sequence[float], top_k: int
    ) -> list[tuple[str, float]]:
        rows = self._packs.get(pack_version, [])
        scored = [(code, cosine(vector, v)) for code, v in rows]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(c, s) for c, s in scored[:top_k] if s > 0]
