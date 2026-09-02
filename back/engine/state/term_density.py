"""⑧ 용어 밀도 게이지. 경보가 아니라 상태 표시(low·normal·high)다.

팩의 `jargon_terms` 목록 대조로만 센다 (rulepack.schema.json: 게이지는 결정적이어야 함).
L0 치환을 거친 은행원 발화에서 용어가 몇 번 나왔는지를 `SessionState.recent_utterances`
창 안에서 합산한다. fold(저장 이벤트)와 observe(실시간)가 같은 창을 보므로 같은 값이 나온다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from contracts.engine_contract import Utterance
from engine.pack.compiler import CompiledPack
from engine.tiers.l0_normalize import normalize

Level = Literal["low", "normal", "high"]

HIGH_AT = 3  # 창 안 은행원 발화에 전문용어가 이만큼 쌓이면 high
LOW_AFTER = 3  # 은행원 발화가 이만큼 이어지는 동안 용어가 하나도 없으면 low


def count_terms(text: str, compiled: CompiledPack) -> int:
    """STT 오인식을 L0 로 바로잡은 뒤 센다. 긴 용어부터 지워 부분 문자열이 두 번 세이지 않게."""
    if not compiled.jargon_terms:
        return 0
    text, _ = normalize(text, compiled.jargon)
    n = 0
    for term in sorted(compiled.jargon_terms, key=len, reverse=True):
        hits = text.count(term)
        if hits:
            n += hits
            text = text.replace(term, " ")
    return n


def level(recent: Sequence[Utterance], compiled: CompiledPack) -> Level:
    teller = [u for u in recent if u.speaker == "teller"]
    if not teller:
        return "normal"  # 아직 잴 것이 없다
    total = sum(count_terms(u.text, compiled) for u in teller)
    if total >= HIGH_AT:
        return "high"
    if total == 0 and len(teller) >= LOW_AFTER:
        return "low"
    return "normal"
