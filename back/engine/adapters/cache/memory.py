"""메모리 판정 캐시. 프로세스 안에서만 산다."""

from __future__ import annotations

from contracts.engine_contract import JudgeDecision


class MemoryDecisionCache:
    def __init__(self) -> None:
        self._store: dict[str, JudgeDecision] = {}

    def get(self, cache_key: str) -> JudgeDecision | None:
        return self._store.get(cache_key)

    def put(self, cache_key: str, decision: JudgeDecision) -> None:
        self._store[cache_key] = decision
