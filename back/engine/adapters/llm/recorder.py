"""L3 녹화·재생. trace 모드에서 LLM 호출 없이 같은 세션을 다시 그린다 (계약 P5).

decide 호출 단위로 cache_key → JudgeDecision 을 JSONL 에 남긴다. DESIGN D2 는 chat model
호출 단위 녹화를 적었지만 교정(Corrector)은 실패해도 원문 유지라 재생에 영향이 없어,
결정이 갈리는 지점인 decide 만 녹화해도 재생이 같다.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from contracts.engine_contract import (
    AlertPayload,
    AssistPayload,
    Comparison,
    Evidence,
    JudgeDecision,
    JudgePrompt,
    LlmJudge,
    VerdictPayload,
)
from engine.errors import LlmUnavailable


class RecordingLlmJudge:
    """실물 judge 를 감싸 결정을 파일에 남긴다. 같은 key 는 마지막 것이 이긴다."""

    def __init__(self, inner: LlmJudge, path: str | Path) -> None:
        self.inner = inner
        self.path = Path(path)
        self.model = getattr(inner, "model", type(inner).__name__)

    def decide(self, prompt: JudgePrompt) -> JudgeDecision:
        decision = self.inner.decide(prompt)
        # cache_key 에 모델명이 들어가므로 재생기가 같은 이름을 써야 키가 맞는다
        row = {"model": self.model, "cache_key": prompt.cache_key, "decision": _encode(decision)}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return decision


class ReplayLlmJudge:
    """녹화 파일로만 답한다. 녹화에 없는 발화는 LlmUnavailable → 잠정 판정 유지."""

    def __init__(self, path: str | Path) -> None:
        self.model = "replay"
        self.decisions: dict[str, JudgeDecision] = {}
        with Path(path).open(encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                self.model = row.get("model", self.model)
                self.decisions[row["cache_key"]] = _decode(row["decision"])

    def decide(self, prompt: JudgePrompt) -> JudgeDecision:
        hit = self.decisions.get(prompt.cache_key)
        if hit is None:
            raise LlmUnavailable(f"녹화에 없는 cache_key: {prompt.cache_key[:12]}…")
        return hit


def _encode(d: JudgeDecision) -> dict:
    return asdict(d)


def _decode(raw: dict) -> JudgeDecision:
    def evidence(e):
        return Evidence(**{**e, "bbox": tuple(e["bbox"]) if e.get("bbox") else None}) if e else None

    verdicts = tuple(
        VerdictPayload(
            **{
                **v,
                "missing_elements": tuple(v.get("missing_elements", ())),
                "evidence": evidence(v.get("evidence")),
            }
        )
        for v in raw.get("verdicts", ())
    )
    alerts = tuple(
        AlertPayload(
            **{
                **a,
                "comparison": Comparison(**a["comparison"]) if a.get("comparison") else None,
                "evidence": evidence(a.get("evidence")),
            }
        )
        for a in raw.get("alerts", ())
    )
    assists = tuple(
        AssistPayload(**{**x, "evidence": evidence(x.get("evidence"))})
        for x in raw.get("assists", ())
    )
    return JudgeDecision(
        verdicts=verdicts, alerts=alerts, assists=assists, tokens=raw.get("tokens")
    )
