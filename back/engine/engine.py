"""Engine 구현체.

judge 는 tiers 를 직접 잇고, refine 은 graphs/refine, assist 는 graphs/assist 가 맡는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from contracts.engine_contract import (
    BUDGET_L3_MS,
    AlertPayload,
    AssistPayload,
    ChunkIndex,
    DecisionCache,
    Embedder,
    JudgeResult,
    LlmJudge,
    Mode,
    TierTrace,
    Utterance,
    VectorIndex,
    VerdictPayload,
)
from engine.assist import briefing as _briefing
from engine.assist import documents as _documents
from engine.budget import Stopwatch
from engine.errors import warn_dummy
from engine.pack.compiler import CompiledPack, compile_pack
from engine.pack.loader import load_pack
from engine.pack.source import PackSource
from engine.state import apply as _apply
from engine.state import fold as _fold
from engine.state import initial as _initial
from engine.state import summary as _summary
from engine.tiers.l0_normalize import normalize
from engine.tiers.l1 import matcher, numeric
from engine.tiers.l1.gate import gate
from engine.tiers.l2 import searcher
from engine.types import RulePack, SessionState


class RuleEngine:
    def __init__(
        self,
        pack_source: PackSource,
        embedder: Embedder | None = None,
        index: VectorIndex | None = None,
        chunks: ChunkIndex | None = None,
        llm: LlmJudge | None = None,
        cache: DecisionCache | None = None,
        corrector: object | None = None,
        generator: object | None = None,
        l3_budget_ms: float = BUDGET_L3_MS,
    ) -> None:
        self.pack_source = pack_source
        self.l3_budget_ms = l3_budget_ms
        self.corrector = corrector
        self.generator = generator
        self._graph = None
        self._assist = None
        self.embedder = embedder
        self.index = index
        self.chunks = chunks
        self.llm = llm
        self.cache = cache
        self._compiled: dict[str, CompiledPack] = {}
        self._warned: set[str] = set()

    # --- 팩·상태 ---------------------------------------------------------
    def load_pack(self, pack_version: str) -> RulePack:
        dim = self.embedder.dim if self.embedder is not None else None
        pack = load_pack(self.pack_source, pack_version, embedder_dim=dim)
        self.compiled(pack)
        return pack

    def compiled(self, pack: RulePack) -> CompiledPack:
        cp = self._compiled.get(pack.pack_version)
        if cp is None:
            raw = self.pack_source.read(pack.pack_version)
            cp = compile_pack(raw, pack)
            self._compiled[pack.pack_version] = cp
            if self.embedder is not None and hasattr(self.index, "add_pack"):
                self.index.add_pack(pack, self.embedder)
        return cp

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

    def observe(self, state: SessionState, utterance: Utterance) -> SessionState:
        """계약 밖 보조 함수. 발화를 상태에 접는다(recent_utterances·⑧ 용어 밀도).

        apply(state, result) 는 발화를 받지 않아 실시간 경로가 이것 없이는 fold 와 갈라진다."""
        return _apply.observe(state, utterance, self._compiled_for(state.pack_version))

    def fold(self, events: Sequence[dict]) -> SessionState:
        started = next(e for e in events if e["kind"] == "session_started")
        return _fold.fold(events, self._compiled_for(started["pack_version"]))

    def _compiled_for(self, pack_version: str) -> CompiledPack:
        cp = self._compiled.get(pack_version)
        if cp is None:
            self.load_pack(pack_version)
            cp = self._compiled[pack_version]
        return cp

    def summarize(self, state: SessionState, pack: RulePack, events: Sequence[dict] = ()) -> dict:
        """계약 밖 보조 함수. session_ended.summary 를 만든다."""
        return _summary.summarize(state, pack, events)

    # --- 판정 -------------------------------------------------------------
    def judge(self, utterance: Utterance, pack: RulePack, state: SessionState) -> JudgeResult:
        """L0 치환 → L1 규칙 → L2 의미검색.

        잠정 판정을 즉시 돌려주고 L3 가 필요하면 needs_refine 을 켠다."""
        compiled = self.compiled(pack)
        sw = Stopwatch()
        g = gate(utterance)
        ref = utterance.utterance_id
        verdicts: list[VerdictPayload] = []
        alerts: list[AlertPayload] = []
        assists: list[AssistPayload] = []
        l1_codes: set[str] = set()
        needs_refine = False
        l2_candidates = 0

        with sw.lap("l1"):
            text, _replacements = normalize(utterance.text, compiled.jargon)
            hits = matcher.match(text, pack, compiled, g.types)
            said_units = {unit for _, unit, _ in numeric.said_numbers(text)}
            for hit in hits:
                item = hit.item
                if not hit.topical:
                    continue  # 숫자만 맞음. 어느 항목의 숫자인지 모른다
                if item.type == "required":
                    has_number = any(
                        r.fact.unit in said_units for r in compiled.numeric.get(item.code, ())
                    )
                    v = matcher.required_verdict(
                        hit, state.state_of(item.code, "omission"), ref, numeric_context=has_number
                    )
                    if v is None and not has_number:
                        continue  # 주제 언급만. L2 가 의미로 다시 본다
                    l1_codes.add(item.code)
                    if v is not None:
                        verdicts.append(v)
                        needs_refine |= v.state == "partial"
                    continue
                l1_codes.add(item.code)
                if item.type == "forbidden":
                    v, alert = matcher.forbidden_verdict(
                        hit, state.state_of(item.code, "commission"), ref
                    )
                    alerts.append(alert)
                    if v is not None:
                        verdicts.append(v)
                        needs_refine = True
                elif item.type == "risk":
                    alerts.append(matcher.risk_alert(hit, ref))
            if "required" in g.types:
                required_hits = [
                    h.item for h in hits if h.type_is("required") and h.item.code in l1_codes
                ]
                alerts.extend(numeric.check(text, required_hits, compiled, ref))
            if g.low_confidence:
                # 은행원인지 확실하지 않다. 건드린 항목은 현재 상태 그대로 verdict 로 남긴다 (P3)
                for hit in matcher.match(text, pack, compiled, frozenset({"required"})):
                    cur = state.state_of(hit.item.code, "omission")
                    if cur is not None:
                        verdicts.append(
                            VerdictPayload(
                                item_code=cur.item_code,
                                axis="omission",
                                state=cur.state,
                                decided_by="L1",
                                missing_elements=cur.missing_elements,
                                utterance_ref=ref,
                                evidence=hit.item.evidence,
                            )
                        )

        if g.types and self.embedder is not None and self.index is not None:
            with sw.lap("l2"):
                r = searcher.search(
                    utterance,
                    text,
                    pack,
                    compiled,
                    state,
                    self.embedder,
                    self.index,
                    g.types,
                    l1_codes,
                )
            verdicts.extend(v for v in r.verdicts if not _same_state(v, state))
            alerts.extend(r.alerts)
            assists.extend(r.assists)
            l2_candidates = len(r.candidates)
            needs_refine |= bool(r.candidates) or any(v.state == "suspected" for v in r.verdicts)
        elif g.types:
            self._warn_once("임베더·인덱스 없음 → L2 생략. 돌려 말한 발화는 잡히지 않는다")

        return JudgeResult(
            verdicts=tuple(verdicts),
            alerts=tuple(_dedupe_alerts(alerts)),
            assists=tuple(assists),
            needs_refine=needs_refine,
            trace=TierTrace(
                l1_ms=round(sw.ms.get("l1", 0.0), 3),
                l2_ms=round(sw.ms.get("l2", 0.0), 3),
                l1_hits=len(hits),
                l2_candidates=l2_candidates,
            ),
        )

    async def refine(
        self, utterance: Utterance, pack: RulePack, state: SessionState
    ) -> JudgeResult:
        """L3 보정. judge 가 잠정으로 남긴 것을 LLM 이 다시 판정한다. LLM 이 없으면 빈 결과."""
        if self.llm is None:
            self._warn_once("LLM 없음 → refine 생략. 잠정 판정이 그대로 확정된다")
            return JudgeResult()
        compiled = self.compiled(pack)
        out = await self._refine_graph().ainvoke(
            {"utterance": utterance, "pack": pack, "compiled": compiled, "session": state}
        )
        return out["result"]

    def _refine_graph(self):
        if self._graph is None:
            from engine.graphs.refine.graph import build_graph
            from engine.graphs.refine.nodes import Deps

            self._graph = build_graph(
                Deps(
                    self.llm,
                    self.cache,
                    self.embedder,
                    self.index,
                    self.corrector,
                    budget_ms=self.l3_budget_ms,
                )
            )
        return self._graph

    # --- assist ------------------------------------------------------------
    def answer(self, question: str, pack: RulePack, state: SessionState) -> AssistPayload | None:
        """기능 ①⑩. 팩 항목 → 문서 본문 순으로 근거를 찾고, 없으면 None (P4)."""
        out = self._assist_graph().invoke(
            {
                "mode": "answer",
                "question": question,
                "pack": pack,
                "compiled": self.compiled(pack),
                "session": state,
            }
        )
        return out["result"]

    def rephrase(
        self, source: Utterance, pack: RulePack, state: SessionState
    ) -> AssistPayload | None:
        """기능 ⑥-B. 직전 은행원 발화가 건드린 항목의 쉬운 말. 없으면 None."""
        out = self._assist_graph().invoke(
            {
                "mode": "rephrase",
                "source": source,
                "pack": pack,
                "compiled": self.compiled(pack),
                "session": state,
            }
        )
        return out["result"]

    def _assist_graph(self):
        if self._assist is None:
            from engine.graphs.assist.graph import build_graph
            from engine.graphs.assist.nodes import Deps

            self._assist = build_graph(Deps(self.embedder, self.index, self.chunks, self.generator))
        return self._assist

    def briefing(
        self, pack: RulePack, customer_type: Literal["general", "professional"]
    ) -> AssistPayload:
        return _briefing.briefing(pack, customer_type)

    def documents(self, pack: RulePack, state: SessionState) -> AssistPayload:
        return _documents.documents(pack, state)

    def _warn_once(self, message: str) -> None:
        if message not in self._warned:
            self._warned.add(message)
            warn_dummy(message)


def _same_state(v: VerdictPayload, state: SessionState) -> bool:
    cur = state.state_of(v.item_code, v.axis)
    return cur is not None and cur.state == v.state


def _dedupe_alerts(alerts: list[AlertPayload]) -> list[AlertPayload]:
    seen: set[tuple[str, str | None]] = set()
    out = []
    for a in alerts:
        key = (a.alert_type, a.item_code)
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out
