"""조립. M1 이 부팅할 때 한 번 부른다 (계약 변경 요청 3번: pack_source 추가)."""

from __future__ import annotations

from contracts.engine_contract import (
    BUDGET_L3_MS,
    ChunkIndex,
    DecisionCache,
    Embedder,
    LlmJudge,
    VectorIndex,
)
from engine.engine import RuleEngine
from engine.pack.source import PackSource


def build_engine(
    pack_source: PackSource,
    embedder: Embedder | None = None,
    index: VectorIndex | None = None,
    chunks: ChunkIndex | None = None,
    llm: LlmJudge | None = None,
    cache: DecisionCache | None = None,
    *,
    l3_budget_ms: float = BUDGET_L3_MS,
) -> RuleEngine:
    """l3_budget_ms 는 계약 상수가 기본. 실측·합의 값으로 덮어쓴다 (DESIGN 10절)."""
    return RuleEngine(pack_source, embedder, index, chunks, llm, cache, l3_budget_ms=l3_budget_ms)
