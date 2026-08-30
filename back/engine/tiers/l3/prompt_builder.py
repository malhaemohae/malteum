"""JudgePrompt 조립과 cache_key. 프롬프트 문자열은 어댑터가 만들고 여기서는 구조만 채운다.

recent_context 는 문자열이라 각 줄 앞에 [은행원]·[고객] 라벨을 붙인다.
같은 문장이라도 화자가 다르면 cache_key 도 달라진다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from contracts.engine_contract import JudgePrompt, Speaker
from engine.types import RulePack, SessionState

_LABEL = {"teller": "[은행원]", "customer": "[고객]", "system": "[시스템]"}


def build(
    text: str,
    pack: RulePack,
    state: SessionState,
    candidate_codes: Sequence[str],
    model: str,
    speaker: Speaker,
) -> JudgePrompt:
    items = tuple(it for c in candidate_codes if (it := pack.item(c)) is not None)
    states = tuple(s for s in state.items if s.item_code in candidate_codes)
    context = tuple(f"{_LABEL[u.speaker]} {u.text}" for u in state.recent_utterances)
    key_source = {
        "pack": pack.pack_version,
        "model": model,
        "text": text,
        "speaker": speaker,
        "context": context,
        "items": [it.code for it in items],
        "states": [(s.item_code, s.axis, s.state, s.missing_elements) for s in states],
        "customer": state.customer_type,
    }
    cache_key = hashlib.sha256(
        json.dumps(key_source, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return JudgePrompt(
        utterance_text=text,
        speaker=speaker,
        recent_context=context,
        candidate_items=items,
        current_states=states,
        customer_type=state.customer_type,
        cache_key=cache_key,
    )
