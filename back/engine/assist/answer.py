"""규정 질문의 검색과 답변 생성.

검색은 LLM 없이 근거 후보를 만들고, 생성은 그 후보 안에서만 답변을 만든다. 외부 계약에
두 기능을 따로 노출하기 전에도 M2 안에서 각각 검증하고 조립할 수 있는 경계다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from contracts.engine_contract import AssistPayload, ChunkIndex, Embedder, Evidence, VectorIndex
from engine.pack.compiler import CompiledPack
from engine.tiers.l2.searcher import fused_scores
from engine.types import RulePack, SessionState

THRESHOLD_ITEM = 0.55
THRESHOLD_CHUNK = 0.5
TOP_K = 3


class Generator(Protocol):
    def generate(self, question: str, evidence_texts: list[str]) -> str: ...


@dataclass(frozen=True, slots=True)
class AnswerSource:
    """검색된 답변 근거 하나. 생성 결과를 검사할 승인 문장도 함께 보존한다."""

    text: str
    evidence: Evidence
    item_code: str | None = None
    allowed_texts: tuple[str, ...] = ()


def search(
    question: str,
    pack: RulePack,
    session: SessionState,
    compiled: CompiledPack,
    embedder: Embedder | None,
    index: VectorIndex | None,
    chunks: ChunkIndex | None,
) -> tuple[AnswerSource, ...]:
    """팩 항목을 먼저 찾고, 없으면 문서 본문에서 근거를 찾는다. LLM은 호출하지 않는다."""
    del session  # 현재 검색은 상태를 사용하지 않지만 호출 경계에는 세션 문맥을 보존한다.
    if embedder is None:
        return ()
    if index is not None:
        sources = []
        for code, similarity in fused_scores(question, pack, compiled, embedder, index)[:TOP_K]:
            item = pack.item(code)
            if item is None or similarity < THRESHOLD_ITEM:
                continue
            text = item.plain_language[0] if item.plain_language else item.evidence.span
            sources.append(
                AnswerSource(
                    text=text,
                    evidence=item.evidence,
                    item_code=item.code,
                    allowed_texts=(item.evidence.span, *item.plain_language),
                )
            )
        if sources:
            return tuple(sources)
    if chunks is None:
        return ()
    vector = embedder.encode([question])[0]
    return tuple(
        AnswerSource(
            text=chunk.text,
            evidence=Evidence(chunk.doc_id, chunk.page, chunk.text, chunk.bbox),
        )
        for chunk, similarity in chunks.search(vector, TOP_K)
        if similarity >= THRESHOLD_CHUNK
    )


def generate(
    question: str,
    sources: tuple[AnswerSource, ...],
    generator: Generator | None,
) -> AssistPayload | None:
    """첫 검색 근거로 답변을 만들고, 생성 문장이 근거 밖이면 버린다."""
    if not sources:
        return None
    source = sources[0]
    text = source.text
    if generator is not None:
        text = generator.generate(question, [source.evidence.span, source.text])
        allowed = source.allowed_texts or (source.evidence.span, source.text)
        if not _grounded(text, allowed):
            return None
    return AssistPayload(
        assist_type="answer",
        text=text,
        item_code=source.item_code,
        trigger="teller_typed",
        evidence=source.evidence,
    )


def _grounded(text: str, allowed: tuple[str, ...]) -> bool:
    """생성 문장의 숫자와 긴 어절이 검색 근거·승인 문장에 있는지 확인한다."""
    tokens = re.findall(r"\d+(?:\.\d+)?%?|[가-힣]{5,}", text)
    if not tokens:
        return any(text.strip() in candidate for candidate in allowed)
    return all(any(token in candidate for candidate in allowed) for token in tokens)
