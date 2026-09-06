"""assist 그래프의 노드: route → retrieve → generate → guard.

MVP 의 generate 는 LLM 없이 팩의 plain_language·evidence·문서 청크 문장을 그대로 쓴다.
그래서 P4(근거 없는 문장을 만들지 않는다)가 구조로 보장된다. LLM 생성은 Generator 를 끼우면 된다.
"""

from __future__ import annotations

from contracts.engine_contract import (
    AssistPayload,
    ChunkIndex,
    Embedder,
    Evidence,
    PackItem,
    VectorIndex,
)
from engine.assist import answer
from engine.graphs.assist.state import AssistState
from engine.tiers.l0_normalize import normalize
from engine.tiers.l1 import matcher
from engine.tiers.l2.searcher import fused_scores


class Deps:
    def __init__(
        self,
        embedder: Embedder | None,
        index: VectorIndex | None,
        chunks: ChunkIndex | None,
        generator: answer.Generator | None = None,
    ) -> None:
        self.embedder = embedder
        self.index = index
        self.chunks = chunks
        self.generator = generator


def make_nodes(deps: Deps):
    def route(s: AssistState) -> AssistState:
        return {
            "items": [],
            "chunks": [],
            "sources": [],
            "text": None,
            "evidence": None,
            "item_code": None,
        }

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
                items = _items_by_similarity(text, pack, compiled, deps)
            return {"items": items}
        return {
            "sources": list(
                answer.search(
                    s["question"],
                    pack,
                    s["session"],
                    compiled,
                    deps.embedder,
                    deps.index,
                    deps.chunks,
                )
            )
        }

    def generate(s: AssistState) -> AssistState:
        if s["mode"] == "answer":
            return {"result": answer.generate(s["question"], tuple(s["sources"]), deps.generator)}
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
        return {"text": text, "evidence": evidence, "item_code": items[0].code if items else None}

    def guard(s: AssistState) -> AssistState:
        """P4. 근거가 없거나, 생성 문장이 근거·팩 문장 밖의 내용을 담으면 None."""
        if s["mode"] == "answer":
            return {}
        text, evidence = s.get("text"), s.get("evidence")
        if not text or evidence is None:
            return {"result": None}
        allowed = [evidence.span]
        if s.get("item_code"):
            it = s["pack"].item(s["item_code"])
            allowed.extend(it.plain_language)
        if s["mode"] == "rephrase":
            payload = AssistPayload(
                assist_type="rephrase",
                text=text,
                item_code=s.get("item_code"),
                trigger="manual_button",
                source_utterance_ref=s["source"].utterance_id,
                evidence=evidence,
            )
        return {"result": payload}

    return route, retrieve, generate, guard


def _items_by_similarity(text: str, pack, compiled, deps: Deps) -> list[PackItem]:
    out = []
    for code, sim in fused_scores(text, pack, compiled, deps.embedder, deps.index)[: answer.TOP_K]:
        it = pack.item(code)
        if it is not None and sim >= answer.THRESHOLD_ITEM:
            out.append(it)
    return out
