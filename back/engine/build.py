"""조립. M1 이 부팅할 때 한 번 부른다 (계약 변경 요청 3번: pack_source 추가)."""

from __future__ import annotations

from contracts.engine_contract import DecisionCache, Embedder, LlmJudge, VectorIndex
from engine.engine import RuleEngine
from engine.pack.source import PackSource


def build_engine(
    pack_source: PackSource,
    embedder: Embedder | None = None,
    index: VectorIndex | None = None,
    llm: LlmJudge | None = None,
    cache: DecisionCache | None = None,
) -> RuleEngine:
    return RuleEngine(pack_source, embedder, index, llm, cache)
