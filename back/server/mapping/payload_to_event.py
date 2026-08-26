"""engine payload(dataclass) → events 본문(dict). 봉투는 envelope.wrap 이 씌운다."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from contracts.engine_contract import (
    AlertPayload,
    AssistPayload,
    Evidence,
    Utterance,
    VerdictPayload,
)


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != ()}


def _evidence(e: Evidence | None) -> dict[str, Any] | None:
    if e is None:
        return None
    d = _drop_none(asdict(e))
    if "bbox" in d:
        d["bbox"] = list(d["bbox"])
    return d


def utterance_body(u: Utterance) -> dict[str, Any]:
    d = _drop_none(asdict(u))
    d.pop("utterance_id")
    return d


def verdict_body(v: VerdictPayload) -> dict[str, Any]:
    d = _drop_none(asdict(v))
    d.pop("supersedes", None)  # 봉투 필드. registry 가 채운다 (D9)
    if v.evidence:
        d["evidence"] = _evidence(v.evidence)
    if v.missing_elements:
        d["missing_elements"] = list(v.missing_elements)
    return d


def alert_body(a: AlertPayload) -> dict[str, Any]:
    d = _drop_none(asdict(a))
    if a.evidence:
        d["evidence"] = _evidence(a.evidence)
    return d


def assist_body(a: AssistPayload) -> dict[str, Any]:
    d = _drop_none(asdict(a))
    d.pop("supersedes", None)
    if a.evidence:
        d["evidence"] = _evidence(a.evidence)
    return d
