"""로컬 임베더 (sentence-transformers). M3 가 팩 발행에 쓰는 것과 같은 모델을 CPU 로 돈다.

e5 계열은 비대칭 프리픽스를 요구한다 — M3 는 팩 항목을 "passage: " 로 넣었고(rulepack/embedding.py),
발화 질의는 "query: " 를 붙인다. MemoryVectorIndex 가 항목을 이 어댑터로 다시 임베딩하는 MVP
경로에서는 양쪽 다 query 프리픽스가 되지만, pgvector 로 넘어가면 항목 벡터는 M3 것을 그대로 쓴다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from engine.errors import LlmUnavailable


class LocalStEmbedder:
    def __init__(
        self,
        model: str = "intfloat/multilingual-e5-small",
        dim: int = 384,
        *,
        prefix: str | None = "query",
    ) -> None:
        self.model = model
        self.dim = dim
        self.prefix = prefix
        self._model: Any = None

    def _load(self) -> Any:
        # 지연 로딩. 서버 부팅·테스트 수집 단계에서 500MB 를 읽지 않는다
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise LlmUnavailable("sentence-transformers 가 설치돼 있지 않음") from e
            self._model = SentenceTransformer(self.model, device="cpu")
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts, self.prefix)

    def encode_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """팩 항목·문서 조각용. e5 는 질의(query)와 대상(passage) 프리픽스가 다르다."""
        return self._encode(texts, "passage" if self.prefix else None)

    def _encode(self, texts: Sequence[str], prefix: str | None) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        prefixed = [f"{prefix}: {t}" if prefix else t for t in texts]
        vectors = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
        out = [[float(x) for x in v] for v in vectors]
        bad = next((len(v) for v in out if len(v) != self.dim), None)
        if bad is not None:
            raise LlmUnavailable(f"{self.model}: 임베딩 차원 {bad} ≠ 설정 {self.dim}")
        return out
