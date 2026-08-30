"""refine 그래프의 노드. 얇다. 로직은 tiers 에 있다."""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

from contracts.engine_contract import (
    BUDGET_L3_MS,
    DecisionCache,
    Embedder,
    JudgeDecision,
    JudgeResult,
    LlmJudge,
    TierTrace,
    VectorIndex,
)
from engine.errors import LlmUnavailable, log
from engine.graphs.refine.state import RefineState
from engine.tiers.l0_normalize import normalize
from engine.tiers.l1 import matcher, memory_search
from engine.tiers.l1.gate import gate
from engine.tiers.l2 import searcher
from engine.tiers.l3 import decision_parser, prompt_builder


class Corrector(Protocol):
    """LLM 전사 교정. 후보 (어절, 용어) 중에서 고르기만 한다. 계약 밖, engine 내부 Protocol."""

    def correct(
        self, text: str, candidates: list[tuple[str, str, float]]
    ) -> list[tuple[str, str]]: ...


class Deps:
    def __init__(
        self,
        llm: LlmJudge,
        cache: DecisionCache | None,
        embedder: Embedder | None,
        index: VectorIndex | None,
        corrector: Corrector | None,
        budget_ms: float = BUDGET_L3_MS,
    ) -> None:
        self.llm = llm
        self.cache = cache
        self.embedder = embedder
        self.index = index
        self.corrector = corrector
        self.budget_ms = budget_ms
        self.model = getattr(llm, "model", type(llm).__name__)


def make_nodes(deps: Deps):
    def candidates(s: RefineState) -> RefineState:
        """judge 와 같은 계산을 다시 해서 L3 대상 항목을 고른다. 숨은 상태를 두지 않기 위해서다."""
        utt, pack, compiled, session = s["utterance"], s["pack"], s["compiled"], s["session"]
        g = gate(utt)
        text, _ = normalize(utt.text, compiled.jargon)
        codes: list[str] = []
        l1_codes: set[str] = set()
        for hit in matcher.match(text, pack, compiled, g.types):
            l1_codes.add(hit.item.code)
            if hit.item.type == "required":
                cur = session.state_of(hit.item.code, "omission")
                if cur is None or cur.state != "met":
                    codes.append(hit.item.code)
            elif hit.item.type == "forbidden":
                cur = session.state_of(hit.item.code, "commission")
                if cur is None or cur.state != "violated":
                    codes.append(hit.item.code)
        if g.types and deps.embedder is not None and deps.index is not None:
            r = searcher.search(
                utt, text, pack, compiled, session, deps.embedder, deps.index, g.types, l1_codes
            )
            codes.extend(c for c in r.candidates if c not in codes)
            codes.extend(
                v.item_code
                for v in r.verdicts
                if v.state == "suspected" and v.item_code not in codes
            )
        if utt.speaker == "teller":
            # judge 가 잠정 suspected 로 남긴 금지 항목은 L3 가 확정해야 한다
            for st in session.items:
                if (
                    st.axis == "commission"
                    and st.state == "suspected"
                    and st.item_code not in codes
                ):
                    codes.append(st.item_code)
        terms = memory_search.candidates(text, compiled.jargon) if utt.speaker == "teller" else []
        return {"text": text, "candidates": codes, "term_candidates": terms, "corrections": []}

    def correct(s: RefineState) -> RefineState:
        if deps.corrector is None or not s["term_candidates"]:
            return {}
        picks = deps.corrector.correct(s["text"], s["term_candidates"])
        allowed = {(w, t) for w, t, _ in s["term_candidates"]}
        applied = [(w, t) for w, t in picks if (w, t) in allowed]
        text = s["text"]
        for w, t in applied:
            text = text.replace(w, t)
        return {"text": text, "corrections": applied}

    def cache_lookup(s: RefineState) -> RefineState:
        prompt = prompt_builder.build(
            s["text"], s["pack"], s["session"], s["candidates"], deps.model, s["utterance"].speaker
        )
        hit = deps.cache.get(prompt.cache_key) if deps.cache is not None else None
        out: RefineState = {"prompt": prompt, "cache_hit": hit is not None}
        if hit is not None:
            out["decision"] = JudgeDecision(
                verdicts=hit.verdicts,
                alerts=hit.alerts,
                assists=hit.assists,
                tokens=hit.tokens,
                from_cache=True,
            )
        return out

    async def l3_judge(s: RefineState) -> RefineState:
        t0 = time.perf_counter()
        try:
            decision = await asyncio.wait_for(
                asyncio.to_thread(deps.llm.decide, s["prompt"]), timeout=deps.budget_ms / 1000
            )
            exceeded = False
        except TimeoutError:
            log.warning("L3 예산 %sms 초과 → 잠정 판정 유지", deps.budget_ms)
            decision, exceeded = JudgeDecision(), True
        except LlmUnavailable as e:
            log.warning("L3 호출 실패 → 잠정 판정 유지: %s", e)
            decision, exceeded = JudgeDecision(), True
        return {
            "decision": decision,
            "l3_ms": (time.perf_counter() - t0) * 1000,
            "budget_exceeded": exceeded,
        }

    def cache_store(s: RefineState) -> RefineState:
        if deps.cache is not None and not s.get("budget_exceeded"):
            deps.cache.put(s["prompt"].cache_key, s["decision"])
        return {}

    def collect(s: RefineState) -> RefineState:
        decision = s.get("decision") or JudgeDecision()
        verdicts, alerts, assists, rejected = decision_parser.parse(
            decision, s["pack"], s["session"], s["utterance"]
        )
        if rejected:
            log.info("L3 결정 일부 거부: %s", rejected)
        result = JudgeResult(
            verdicts=tuple(verdicts),
            alerts=tuple(alerts),
            assists=tuple(assists),
            needs_refine=False,
            trace=TierTrace(
                l3_ms=round(s.get("l3_ms", 0.0), 3),
                l2_candidates=len(s["candidates"]),
                l3_called=not s.get("cache_hit", False) and "l3_ms" in s,
                llm_tokens=decision.tokens,
                cache_hit=s.get("cache_hit", False),
            ),
        )
        return {"result": result}

    return candidates, correct, cache_lookup, l3_judge, cache_store, collect
