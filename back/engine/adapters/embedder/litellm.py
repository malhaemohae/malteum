"""실물 L2 임베더. LiteLLM 으로 provider 의 임베딩 모델을 부른다.

차원은 팩과 맞아야 하고(load_pack 이 검사) 첫 호출에서 실제 차원을 대조한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import litellm

from engine.adapters.llm.litellm import register
from engine.errors import LlmUnavailable


class LiteLlmEmbedder:
    def __init__(
        self,
        model: str,
        dim: int,
        *,
        provider: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.model = register(model, provider, "embedding")
        self.dim = dim
        self.api_key = api_key
        self.api_base = api_base
        self.timeout_s = timeout_s

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = litellm.embedding(
                model=self.model,
                input=list(texts),
                timeout=self.timeout_s,
                api_key=self.api_key,
                api_base=self.api_base,
            )
        except Exception as e:
            raise LlmUnavailable(f"{self.model}: {type(e).__name__}: {e}") from e
        rows = sorted(resp.data, key=lambda d: d["index"])
        vectors = [list(map(float, d["embedding"])) for d in rows]
        bad = next((len(v) for v in vectors if len(v) != self.dim), None)
        if bad is not None:
            raise LlmUnavailable(f"{self.model}: 임베딩 차원 {bad} ≠ 설정 {self.dim}")
        return vectors
