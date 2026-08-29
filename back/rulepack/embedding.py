"""항목 임베딩. 모델은 갈아끼운다.

계약이 `embedding` 을 팩에 묶어 두는 이유가 여기 있다. 모델을 바꾸면 벡터가
달라지므로 팩을 재발행하고, 과거 세션은 과거 팩과 과거 차원을 그대로 쓴다.
그래서 팩에 적히는 `model` · `dim` 은 실제로 벡터를 만든 구현이 스스로 밝혀야
하고, 코드 어딘가에 상수로 박아 두면 안 된다. 박아 두면 벡터를 만든 적도 없는
모델 이름이 팩에 남는다 (2026-08-29 이전이 그랬다).

지금은 결정적 fake 하나만 있다. 실제 모델은 선택이 끝나면 같은 Protocol 로
붙인다. 붙이는 쪽은 `encode` 와 세 속성만 채우면 되고 나머지는 안 바뀐다.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Any, Protocol


class EmbeddingError(RuntimeError):
    """임베딩 생성 실패."""


class EmbeddingModel(Protocol):
    """텍스트를 벡터로 바꾸는 구현.

    `name` 과 `dim` 은 팩에 그대로 기록된다. 실제로 쓴 것과 달라지면 나중에
    어느 모델로 만든 벡터인지 알 수 없게 된다.
    """

    name: str
    dim: int
    normalized: bool
    id_prefix: str

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicFakeEmbedding:
    """해시로 만드는 결정적 벡터. 모델 선택 전까지 CI 와 테스트가 쓴다.

    의미를 담지 않으므로 L2 검색 품질을 보증하지 않는다. 대신 같은 입력에 늘
    같은 값을 내서 `verify --strict` 의 결정적 재실행 검사를 통과하고, 적재
    경로를 실제 모델 없이 끝까지 돌려볼 수 있다.

    팩에 `deterministic-fake` 로 기록되므로 진짜 임베딩과 헷갈리지 않는다.
    """

    name = "deterministic-fake"
    id_prefix = "fake"
    normalized = True

    def __init__(self, dim: int = 384) -> None:
        if dim < 1:
            raise EmbeddingError("dim 은 1 이상이어야 함")
        self.dim = dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        # 해시를 늘려 dim 개의 float 를 뽑는다. 블록 번호를 함께 넣어야 같은
        # 8바이트가 되풀이되지 않는다.
        raw = bytearray()
        block = 0
        seed = text.encode("utf-8")
        while len(raw) < self.dim * 4:
            raw += hashlib.sha256(seed + block.to_bytes(4, "big")).digest()
            block += 1
        values = [
            struct.unpack_from(">i", raw, offset * 4)[0] / 2**31 for offset in range(self.dim)
        ]
        norm = math.sqrt(sum(v * v for v in values))
        if norm == 0:
            raise EmbeddingError("영벡터가 나왔음")
        return [v / norm for v in values]


def embedding_text(item: dict[str, Any]) -> str:
    """항목에서 벡터로 만들 텍스트를 뽑는다.

    L2 는 은행원 발화와 항목을 뜻으로 견준다. 그래서 항목 이름만으로는 부족하고
    요구 요건과 쉬운 말 설명을 함께 넣는다. 근거 원문(`evidence.span`)은 넣지
    않는다. 법령 문장은 표현이 상담 발화와 멀어 검색을 흐린다.
    """
    parts = [item["name"], *item.get("requirement_elements", []), *item.get("plain_language", [])]
    return " ".join(str(p).strip() for p in parts if p)
