"""규정 팩 조회.

상세는 `rulepack.schema.json` 을 그대로 돌려준다(계약 명시). 목록은 그 문서에서 뽑은
요약이다. 원천은 DB 이며, 세션이 쓰는 PackSource 와 다를 수 있다(services/pack_store.py).
"""

from __future__ import annotations

from typing import Any

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


@router.get("/presets", tags=["presets"])
def list_presets() -> dict[str, list[Any]]:
    """심사용 프리셋 목록.

    원천은 `assets/scenarios/<id>/manifest` 다(최상위 README). 지금 그 폴더가 비어 있고
    manifest 형식도 정해지지 않았다(R5 소유). 형식을 지어내지 않고 빈 목록을 돌려준다.
    프런트는 이 경로에 대고 짤 수 있고, 자산이 들어오면 여기만 채우면 된다.
    """
    return {"presets": []}
