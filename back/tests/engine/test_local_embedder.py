"""LocalStEmbedder 의 프리픽스·정규화·차원 검사. 실물 모델 대신 가짜 SentenceTransformer."""

from __future__ import annotations

import pytest

from engine.adapters.embedder.local import LocalStEmbedder
from engine.errors import LlmUnavailable


class FakeSt:
    def __init__(self, dim):
        self.dim = dim
        self.seen = []

    def encode(self, texts, **kw):
        self.seen.extend(texts)
        return [[1.0] * self.dim for _ in texts]


def test_query_prefix_and_dim():
    e = LocalStEmbedder(dim=4)
    e._model = FakeSt(4)
    out = e.encode(["중도해지 되나요"])
    assert e._model.seen == ["query: 중도해지 되나요"]
    assert out == [[1.0, 1.0, 1.0, 1.0]]


def test_dim_mismatch_raises():
    e = LocalStEmbedder(dim=384)
    e._model = FakeSt(8)
    with pytest.raises(LlmUnavailable, match="차원"):
        e.encode(["x"])


def test_empty_input_short_circuits():
    assert LocalStEmbedder().encode([]) == []
