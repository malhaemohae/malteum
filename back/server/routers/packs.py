"""규정 팩 조회와 상담 전 브리핑.

상세는 `rulepack.schema.json` 을 그대로 돌려준다(계약 명시). 목록은 그 문서에서 뽑은
요약이다. 원천은 DB 이며, 세션이 쓰는 PackSource 와 다를 수 있다(services/pack_store.py).

브리핑은 팩을 화면 모양으로 접어 준다. `ready` 가 체크리스트를 만드는 것과 같은 일이고
(mapping/event_to_s2c.py), 문장을 새로 만들지 않으므로 assist 구현이 아니다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request

from server.generated.api import PackSummary

router = APIRouter(tags=["packs"])


@router.get("/packs")
def list_packs(
    request: Request,
    product_code: str | None = None,
    latest_only: bool = False,
) -> dict[str, list[PackSummary]]:
    rows = request.app.state.runtime.pack_store.list(product_code, latest_only)
    return {"packs": [PackSummary.model_validate(r) for r in rows]}


@router.get("/packs/{pack_version}")
def get_pack(pack_version: str, request: Request) -> dict[str, Any]:
    doc = request.app.state.runtime.pack_store.get(pack_version)
    if doc is None:
        raise HTTPException(404, "규정 팩이 없습니다.")
    return doc


@router.get("/packs/{pack_version}/briefing")
def get_briefing(
    pack_version: str,
    request: Request,
    customer_type: Literal["general", "professional"] = "general",
) -> dict[str, Any]:
    """기능 ② 상담 전 브리핑. 세션 시작 전에 한 번 읽는 요약.

    계약이 "팩 발행 시 미리 만들어 캐시" 라고 적었지만 지금 팩에 그 자리가 없다.
    그래서 매번 접어 만들고 `cached=false` 로 정직하게 알린다. LLM 은 부르지 않는다 —
    재료가 전부 팩 안에 있어서 실시간 호출이 필요 없다.

    `customer_type` 은 아직 결과를 가르지 않는다. 팩이 소비자 유형별 문안을 따로 갖고
    있지 않아, 지우지 않고 받아만 둔다(계약이 질의 파라미터로 정의).
    """
    doc = request.app.state.runtime.pack_store.get(pack_version)
    if doc is None:
        raise HTTPException(404, "규정 팩이 없습니다.")

    must_say = []
    must_not_say = []
    documents: list[str] = []
    for it in doc.get("items", []):
        kind = it.get("type")
        if kind == "required":
            entry: dict[str, Any] = {
                "item_code": it["code"],
                "name": it["name"],
                "elements": list(it.get("requirement_elements") or []),
            }
            if it.get("plain_language"):
                entry["plain_language"] = list(it["plain_language"])
            must_say.append(entry)
        elif kind == "forbidden":
            must_not_say.append(
                {
                    "item_code": it["code"],
                    "name": it["name"],
                    "examples": list(it.get("forbidden_examples") or []),
                }
            )
        elif kind == "reference":
            # 기능 ④ 서류 안내. 팩이 필요 서류를 참조 항목의 요소로 들고 있다
            documents.extend(it.get("requirement_elements") or [])

    return {
        "pack_version": doc["pack_version"],
        "must_say": must_say,
        "must_not_say": must_not_say,
        "documents_required": documents,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cached": False,
    }


@router.get("/presets", tags=["presets"])
def list_presets() -> dict[str, list[Any]]:
    """심사용 프리셋 목록.

    원천은 `assets/scenarios/<id>/manifest` 다(최상위 README). 지금 그 폴더가 비어 있고
    manifest 형식도 정해지지 않았다(R5 소유). 형식을 지어내지 않고 빈 목록을 돌려준다.
    프런트는 이 경로에 대고 짤 수 있고, 자산이 들어오면 여기만 채우면 된다.
    """
    return {"presets": []}
