from __future__ import annotations

from typing import Any, Literal, TypedDict

from contracts.engine_contract import Chunk, Evidence, PackItem, Utterance
from engine.pack.compiler import CompiledPack
from engine.types import RulePack, SessionState


class AssistState(TypedDict, total=False):
    mode: Literal["answer", "rephrase"]
    question: str
    source: Utterance
    pack: RulePack
    compiled: CompiledPack
    session: SessionState
    items: list[PackItem]
    chunks: list[Chunk]
    text: str | None
    evidence: Evidence | None
    item_code: str | None
    result: Any
