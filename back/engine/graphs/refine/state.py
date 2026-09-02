from __future__ import annotations

from typing import Any, TypedDict

from contracts.engine_contract import JudgeDecision, JudgePrompt, Utterance
from engine.pack.compiler import CompiledPack
from engine.types import RulePack, SessionState


class RefineState(TypedDict, total=False):
    utterance: Utterance
    pack: RulePack
    compiled: CompiledPack
    session: SessionState
    text: str
    candidates: list[str]
    term_candidates: list[tuple[str, str, float]]
    corrections: list[tuple[str, str]]
    prompt: JudgePrompt
    decision: JudgeDecision
    cache_hit: bool
    l3_ms: float
    budget_exceeded: bool
    result: Any
