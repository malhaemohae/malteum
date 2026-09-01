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
from server.services import publish
from server.services.pack_store import PackAlreadyPublished

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


@router.post("/packs/publish", status_code=201)
def publish_pack(doc: dict[str, Any], request: Request) -> dict[str, Any]:
    """팩 발행. 계약: "M3 가 호출한다. 승인 완료 항목만 담아 새 버전으로 굳힌다."

    **근거 스팬 대조가 이 경로의 존재 이유다**(422). 인용이 원문에 실재하지 않는 항목은
    P4 위반이라 팩째로 거절한다. 대조는 `contracts/find_span.py` 로 한다 — M3 의 발행
    파이프라인도 같은 함수를 쓰므로 그쪽에서 통과한 팩은 여기서도 통과한다.
    """
    settings = request.app.state.settings
    store = request.app.state.runtime.pack_store
    try:
        publish.validate(doc)
    except publish.PublishInvalid as e:
        raise HTTPException(400, str(e)) from e

    rejected = publish.verify_evidence(doc, settings.docs_dir)
    if rejected:
        raise HTTPException(
            422,
            detail={
                "code": "evidence_mismatch",
                "message": "근거가 원문과 맞지 않습니다.",
                "rejected_items": rejected,
            },
        )
    try:
        store.put(doc)
    except PackAlreadyPublished as e:
        raise HTTPException(409, str(e)) from e
    return {
        "pack_version": doc["pack_version"],
        "item_count": len(doc.get("items", ())),
        # 벡터는 임베딩 모델을 쥔 쪽이 넣는다(scripts/load_pack.py). 여기서는 0 이 정직하다
        "embedding_indexed": 0,
    }


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
