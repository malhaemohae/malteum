"""④ 서류 안내. reference 항목의 documents_required 를 조립한다. LLM 없음."""

from __future__ import annotations

from contracts.engine_contract import AssistPayload
from engine.types import RulePack, SessionState


def documents(pack: RulePack, state: SessionState) -> AssistPayload:
    refs = [it for it in pack.items if it.type == "reference" and it.documents_required]
    lines = [f"[{it.name}]\n" + "\n".join(f"- {d}" for d in it.documents_required) for it in refs]
    first = refs[0] if refs else None
    return AssistPayload(
        assist_type="documents",
        text="\n".join(lines) if lines else "필요 서류 정보가 팩에 없습니다",
        item_code=first.code if first else None,
        trigger="session_start",
        evidence=first.evidence if first else None,
    )
