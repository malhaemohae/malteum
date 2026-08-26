"""Engine 구현체. 지금은 팩·상태만 살아 있고 판정·assist 는 NotImplementedError.

judge 는 tiers/ 가, refine 은 graphs/judge/ 가, assist 는 graphs/assist/ 가 생기면 채운다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from contracts.engine_contract import (
    AssistPayload,
    DecisionCache,
    Embedder,
    JudgeResult,
    LlmJudge,
    Mode,
    Utterance,
    VectorIndex,
)
from engine.pack.loader import load_pack
from engine.pack.source import PackSource
from engine.state import apply as _apply
from engine.state import fold as _fold
from engine.state import initial as _initial
from engine.state import summary as _summary
from engine.types import RulePack, SessionState


class RuleEngine:
    def __init__(
        self,
        pack_source: PackSource,
        embedder: Embedder | None = None,
        index: VectorIndex | None = None,
        llm: LlmJudge | None = None,
        cache: DecisionCache | None = None,
    ) -> None:
        self.pack_source = pack_source
        self.embedder = embedder
        self.index = index
        self.llm = llm
        self.cache = cache

    # --- 팩·상태 ---------------------------------------------------------
    def load_pack(self, pack_version: str) -> RulePack:
        dim = self.embedder.dim if self.embedder is not None else None
        return load_pack(self.pack_source, pack_version, embedder_dim=dim)

    def initial_state(
        self,
        session_id: str,
        pack: RulePack,
        mode: Mode,
        customer_type: Literal["general", "professional"] = "general",
    ) -> SessionState:
        return _initial.initial_state(session_id, pack, mode, customer_type)

    def apply(self, state: SessionState, result: JudgeResult) -> SessionState:
        return _apply.apply(state, result)

    def fold(self, events: Sequence[dict]) -> SessionState:
        return _fold.fold(events)

    def summarize(self, state: SessionState, pack: RulePack, events: Sequence[dict] = ()) -> dict:
        """계약 밖 보조 함수. session_ended.summary 를 만든다."""
        return _summary.summarize(state, pack, events)

    # --- 판정 (미구현) -----------------------------------------------------
    def judge(self, utterance: Utterance, pack: RulePack, state: SessionState) -> JudgeResult:
        raise NotImplementedError("tiers/ 미구현")

    async def refine(
        self, utterance: Utterance, pack: RulePack, state: SessionState
    ) -> JudgeResult:
        raise NotImplementedError("graphs/judge 미구현")

    # --- assist (미구현) ---------------------------------------------------
    def answer(self, question: str, pack: RulePack, state: SessionState) -> AssistPayload | None:
        raise NotImplementedError("graphs/assist 미구현")

    def rephrase(
        self, source: Utterance, pack: RulePack, state: SessionState
    ) -> AssistPayload | None:
        raise NotImplementedError("graphs/assist 미구현")

    def briefing(
        self, pack: RulePack, customer_type: Literal["general", "professional"]
    ) -> AssistPayload:
        raise NotImplementedError("graphs/assist 미구현")

    def documents(self, pack: RulePack, state: SessionState) -> AssistPayload:
        raise NotImplementedError("graphs/assist 미구현")
