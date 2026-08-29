"""JudgePrompt 조립과 cache_key. 프롬프트 문자열은 어댑터가 만들고 여기서는 구조만 채운다."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from contracts.engine_contract import JudgePrompt
from engine.types import RulePack, SessionState


def build(
    text: str, pack: RulePack, state: SessionState, candidate_codes: Sequence[str], model: str
) -> JudgePrompt:
    items = tuple(it for c in candidate_codes if (it := pack.item(c)) is not None)
    states = tuple(s for s in state.items if s.item_code in candidate_codes)
    context = tuple(u.text for u in state.recent_utterances)
    key_source = {
        "pack": pack.pack_version,
        "model": model,
        "text": text,
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
        recent_context=context,
        candidate_items=items,
        current_states=states,
        customer_type=state.customer_type,
        cache_key=cache_key,
    )
