"""테스트용 문서 본문 검색. 청크 몇 개를 메모리에 두고 코사인으로 찾는다. 비어 있으면 경고."""

from __future__ import annotations

from collections.abc import Sequence

from contracts.engine_contract import Chunk, Embedder
from engine.adapters.vector_index.memory import cosine
from engine.errors import warn_dummy


class FakeChunkIndex:
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
