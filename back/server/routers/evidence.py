"""근거 원문 (기능 ⑭) 과 그 배경이 될 페이지 이미지.

`evidence_ref` 는 근거를 품은 이벤트의 event_id 다(계약). 그 이벤트에서 doc_id·page·span·
bbox 를 꺼내고, 문서 메타(제목·발행처·스냅샷 일자)는 그 세션이 쓴 팩의 sources 에서 읽는다.
출처와 일자는 화면·리포트에 상시 표기 대상이다.

여기에는 **페이지 렌더만** 있다. 문서 업로드·추출·후보 승인은 M3 파이프라인이고 오너가
정해지지 않았다.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from engine.pack.source import PackNotFound
from server.services.documents import DocumentNotFound, page_size, render

router = APIRouter(tags=["evidence"])


@router.get("/evidence/{evidence_ref}")
def get_evidence(evidence_ref: str, request: Request) -> dict[str, Any]:
    runtime = request.app.state.runtime
    event = runtime.event_store.by_id(evidence_ref)
    if event is None:
        raise HTTPException(404, "그 근거를 찾을 수 없습니다.")
    body = event[event["kind"]]
    evidence = body.get("evidence")
    if not evidence:
        raise HTTPException(404, "이 이벤트에는 근거가 없습니다.")

    try:
        doc = runtime.pack_source.read(event["pack_version"])
    except PackNotFound as e:
        raise HTTPException(404, "규정 팩이 없습니다.") from e
    source = next((s for s in doc.get("sources", []) if s["doc_id"] == evidence["doc_id"]), {})
    try:
        size = page_size(request.app.state.settings.docs_dir, evidence["doc_id"], evidence["page"])
    except DocumentNotFound as e:
        raise HTTPException(404, f"원문 문서가 없습니다: {evidence['doc_id']}") from e

    return {
        "doc_id": evidence["doc_id"],
        "doc_title": source.get("title"),
        "publisher": source.get("publisher"),
        "snapshot_date": source.get("snapshot_date"),
        "page": evidence["page"],
        "span": evidence["span"],
        "bbox": evidence.get("bbox"),
        "legal_basis": evidence.get("legal_basis"),
        "page_image_url": f"/api/documents/{evidence['doc_id']}/pages/{evidence['page']}.png",
        "page_size": list(size),
    }


@router.get("/documents/{doc_id}/pages/{page}.png", tags=["documents"])
def get_page_image(
    doc_id: str,
    page: int,
    request: Request,
    scale: Annotated[float, Query(gt=0, le=4)] = 2.0,
) -> Response:
    try:
        png = render(request.app.state.settings.docs_dir, doc_id, page, scale)
    except DocumentNotFound as e:
        raise HTTPException(404, "그 페이지가 없습니다.") from e
    # 발행된 팩이 가리키는 원문은 바뀌지 않는다. 오래 캐시해도 안전하다
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
