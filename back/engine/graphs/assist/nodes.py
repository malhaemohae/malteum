"""assist 그래프의 노드: route → retrieve → generate → guard.

MVP 의 generate 는 LLM 없이 팩의 plain_language·evidence·문서 청크 문장을 그대로 쓴다.
그래서 P4(근거 없는 문장을 만들지 않는다)가 구조로 보장된다. LLM 생성은 Generator 를 끼우면 된다.
"""

from __future__ import annotations

from typing import Protocol

from contracts.engine_contract import (
    AssistPayload,
    Chunk,
    ChunkIndex,
    Embedder,
    Evidence,
    PackItem,
    VectorIndex,
)
from engine.graphs.assist.state import AssistState
from engine.tiers.l0_normalize import normalize
from engine.tiers.l1 import matcher

THRESHOLD_ITEM = 0.5
THRESHOLD_CHUNK = 0.5
TOP_K = 3


class Generator(Protocol):
    """LLM 문장 생성. 반환 문장은 guard 가 근거와 대조한다. 계약 밖, engine 내부 Protocol."""

    def generate(self, question: str, evidence_texts: list[str]) -> str: ...


class Deps:
    def __init__(
        self,
        embedder: Embedder | None,
        index: VectorIndex | None,
        chunks: ChunkIndex | None,
        generator: Generator | None = None,
    ) -> None:
        self.embedder = embedder
        self.index = index
        self.chunks = chunks
        self.generator = generator


def make_nodes(deps: Deps):
    def route(s: AssistState) -> AssistState:
        return {"items": [], "chunks": [], "text": None, "evidence": None, "item_code": None}

    def retrieve(s: AssistState) -> AssistState:
        pack, compiled = s["pack"], s["compiled"]
        if s["mode"] == "rephrase":
            text, _ = normalize(s["source"].text, compiled.jargon)
            hits = matcher.match(text, pack, compiled, frozenset({"required", "forbidden"}))
            # 요건 요소를 더 많이(비율로) 건드린 항목이 그 발화의 주제다
            ranked = sorted(
                hits,
                key=lambda h: len(h.elements) / max(len(h.item.requirement_elements), 1),
                reverse=True,
            )
            items = [h.item for h in ranked]
            if not items and deps.embedder is not None and deps.index is not None:
                items = _items_by_similarity(text, pack, deps)
            return {"items": items}
        question = s["question"]
        items: list[PackItem] = []
        chunks: list[Chunk] = []
        if deps.embedder is not None:
            vector = deps.embedder.encode([question])[0]
            if deps.index is not None:
                for code, sim in deps.index.search(pack.pack_version, vector, TOP_K):
                    it = pack.item(code)
                    if it is not None and sim >= THRESHOLD_ITEM:
                        items.append(it)
            if not items and deps.chunks is not None:
                chunks = [
                    c for c, sim in deps.chunks.search(vector, TOP_K) if sim >= THRESHOLD_CHUNK
                ]
        return {"items": items, "chunks": chunks}

    def generate(s: AssistState) -> AssistState:
        items, chunks = s["items"], s["chunks"]
        if items:
            it = items[0]
            evidence = it.evidence
            base = it.plain_language[0] if it.plain_language else it.evidence.span
        elif chunks:
            c = chunks[0]
            evidence = Evidence(doc_id=c.doc_id, page=c.page, span=c.text, bbox=c.bbox)
            base = c.text
        else:
            return {"text": None, "evidence": None}
        text = base
        if deps.generator is not None and s["mode"] == "answer":
            text = deps.generator.generate(s["question"], [evidence.span, base])
        return {"text": text, "evidence": evidence, "item_code": items[0].code if items else None}

    def guard(s: AssistState) -> AssistState:
        """P4. 근거가 없거나, 생성 문장이 근거·팩 문장 밖의 내용을 담으면 None."""
        text, evidence = s.get("text"), s.get("evidence")
        if not text or evidence is None:
            return {"result": None}
        allowed = [evidence.span]
        if s.get("item_code"):
            it = s["pack"].item(s["item_code"])
            allowed.extend(it.plain_language)
        if deps.generator is not None and not any(_contained(text, a) for a in allowed):
            return {"result": None}
        if s["mode"] == "rephrase":
            payload = AssistPayload(
                assist_type="rephrase",
                text=text,
                item_code=s.get("item_code"),
                trigger="manual_button",
                source_utterance_ref=s["source"].utterance_id,
                evidence=evidence,
            )
        else:
            payload = AssistPayload(
                assist_type="answer",
                text=text,
                item_code=s.get("item_code"),
                trigger="teller_typed",
                evidence=evidence,
            )
        return {"result": payload}

    return route, retrieve, generate, guard


def _items_by_similarity(text: str, pack, deps: Deps) -> list[PackItem]:
    vector = deps.embedder.encode([text])[0]
    out = []
    for code, sim in deps.index.search(pack.pack_version, vector, TOP_K):
        it = pack.item(code)
        if it is not None and sim >= THRESHOLD_ITEM:
            out.append(it)
    return out


def _contained(text: str, source: str) -> bool:
    """생성 문장의 핵심이 근거 안에 있는가. 숫자와 5자 이상 어절이 모두 근거에 있어야 한다."""
    import re

    tokens = re.findall(r"\d+(?:\.\d+)?%?|[가-힣]{5,}", text)
    return all(t in source for t in tokens) if tokens else text.strip() in source
