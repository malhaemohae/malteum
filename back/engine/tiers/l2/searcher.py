"""L2 의미 검색. 발화 임베딩과 팩 항목의 유사도로 후보를 올린다.

판정 확정은 L3 가 한다. 예외는 되물음(explained)과 위험 신호(alert).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from contracts.engine_contract import (
    AlertPayload,
    AssistPayload,
    Embedder,
    PackItem,
    Utterance,
    VectorIndex,
    VerdictPayload,
)
from engine.pack.compiler import CompiledPack
from engine.types import RulePack, SessionState

THRESHOLD_REQUIRED = 0.5
THRESHOLD_FORBIDDEN = 0.5
THRESHOLD_RISK = 0.5
THRESHOLD_COMPREHENSION = 0.3
TOP_K = 5


@dataclass(frozen=True, slots=True)
class L2Result:
    candidates: tuple[
        str, ...
    ] = ()  # L3 에 넘길 항목 코드 (required 후보 · comprehension 확인 후보)
    verdicts: tuple[VerdictPayload, ...] = ()
    alerts: tuple[AlertPayload, ...] = ()
    assists: tuple[AssistPayload, ...] = ()
    scores: tuple[tuple[str, float], ...] = field(default=())


def search(
    utterance: Utterance,
    text: str,
    pack: RulePack,
    compiled: CompiledPack,
    state: SessionState,
    embedder: Embedder,
    index: VectorIndex,
    types: frozenset[str],
    l1_codes: set[str],
) -> L2Result:
    vector = embedder.encode([text])[0]
    scores = tuple(index.search(pack.pack_version, vector, TOP_K))
    by_code = {code: item for code, item in ((it.code, it) for it in pack.items)}
    candidates: list[str] = []
    verdicts: list[VerdictPayload] = []
    alerts: list[AlertPayload] = []
    assists: list[AssistPayload] = []
    ref = utterance.utterance_id

    if "required" in types or "forbidden" in types:
        for code, sim in scores:
            item = by_code.get(code)
            if item is None or code in l1_codes:
                continue
            if item.type == "required" and sim >= THRESHOLD_REQUIRED:
                cur = state.state_of(code, "omission")
                if cur is None or cur.state in ("unmet", "partial"):
                    candidates.append(code)
            elif item.type == "forbidden" and sim >= THRESHOLD_FORBIDDEN:
                cur = state.state_of(code, "commission")
                if cur is None or cur.state == "clean":
                    verdicts.append(
                        VerdictPayload(
                            item_code=code,
                            axis="commission",
                            state="suspected",
                            decided_by="L2",
                            utterance_ref=ref,
                            evidence=item.evidence,
                        )
                    )
                    alerts.append(
                        AlertPayload(
                            alert_type="forbidden_phrase",
                            severity="warning",
                            message=f"설명서 기준 확인이 필요합니다: {item.name}",
                            item_code=code,
                            utterance_ref=ref,
                            evidence=item.evidence,
                        )
                    )

    if "risk" in types:
        for code, sim in scores:
            item = by_code.get(code)
            if (
                item is not None
                and item.type == "risk"
                and sim >= THRESHOLD_RISK
                and code not in l1_codes
            ):
                alerts.append(
                    AlertPayload(
                        alert_type="risk_signal",
                        severity="critical",
                        message=f"위험 신호: {item.name}. 본인 의사와 거래 목적 확인이 필요합니다",
                        item_code=code,
                        utterance_ref=ref,
                        evidence=item.evidence,
                    )
                )

    if "comprehension" in types:
        if any(rx.search(text) for rx in compiled.reask):
            target = _reask_target(scores, pack, state)
            if target is not None:
                cur = state.state_of(target.code, "comprehension")
                if cur is None or cur.state != "confirmed":
                    verdicts.append(
                        VerdictPayload(
                            item_code=target.code,
                            axis="comprehension",
                            state="explained",
                            decided_by="L2",
                            utterance_ref=ref,
                            evidence=target.evidence,
                        )
                    )
                rephrase = _rephrase_from_plain(target, utterance, state)
                if rephrase is not None:
                    assists.append(rephrase)
        else:
            for code, sim in scores:
                cur = state.state_of(code, "comprehension")
                if cur is not None and cur.state == "explained" and sim >= THRESHOLD_COMPREHENSION:
                    candidates.append(code)

    return L2Result(tuple(candidates), tuple(verdicts), tuple(alerts), tuple(assists), scores)


def _reask_target(
    scores: Sequence[tuple[str, float]], pack: RulePack, state: SessionState
) -> PackItem | None:
    """되물음이 어느 항목에 대한 것인가.

    이미 설명된(partial·met) 항목 중 유사도 최고, 없으면 partial 항목 하나."""
    explained = {
        s.item_code for s in state.items if s.axis == "omission" and s.state in ("partial", "met")
    }
    for code, _ in scores:
        if code in explained:
            return pack.item(code)
    partial = [s.item_code for s in state.items if s.axis == "omission" and s.state == "partial"]
    return pack.item(partial[0]) if partial else None


def _rephrase_from_plain(
    item: PackItem, utterance: Utterance, state: SessionState
) -> AssistPayload | None:
    if not item.plain_language:
        return None
    source = next((u for u in reversed(state.recent_utterances) if u.speaker == "teller"), None)
    return AssistPayload(
        assist_type="rephrase",
        text=item.plain_language[0],
        item_code=item.code,
        trigger="customer_reask",
        source_utterance_ref=source.utterance_id if source else utterance.utterance_id,
        evidence=item.evidence,
    )
