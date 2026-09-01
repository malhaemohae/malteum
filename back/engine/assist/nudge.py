"""넛지. partial·unmet 의 빠진 요소로 문구를 조립한다. LLM 없음."""

from __future__ import annotations

from contracts.engine_contract import AssistPayload, PackItem


def nudge(
    item: PackItem, missing: tuple[str, ...], utterance_ref: str | None = None
) -> AssistPayload:
    what = ", ".join(missing) if missing else item.name
    return AssistPayload(
        assist_type="nudge",
        text=f"{item.name}: {what} 안내가 남아 있습니다",
        item_code=item.code,
        trigger="missing_item",
        source_utterance_ref=utterance_ref,
        evidence=item.evidence,
    )
