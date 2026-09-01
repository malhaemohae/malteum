"""② 상담 브리핑. 필수 항목 수와 이름. LLM 없음.

팩 발행 시 미리 만드는 것이 기획이나 MVP 는 조립한다.
"""

from __future__ import annotations

from typing import Literal

from contracts.engine_contract import AssistPayload
from engine.types import RulePack


def briefing(pack: RulePack, customer_type: Literal["general", "professional"]) -> AssistPayload:
    required = pack.required_items()
    names = " · ".join(it.name for it in required)
    who = "일반금융소비자" if customer_type == "general" else "전문금융소비자"
    return AssistPayload(
        assist_type="briefing",
        text=f"{pack.product_name} ({who}) 필수 안내 {len(required)}개: {names}",
        trigger="session_start",
        evidence=required[0].evidence if required else None,
    )
