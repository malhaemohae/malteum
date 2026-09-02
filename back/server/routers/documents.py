"""규정 원문 문서. 목록 · 후보 조회 · 후보 승인.

**업로드(`POST /documents`)와 추출 결과(`/extraction`)는 아직 없다.** 그 둘은
OpenDataLoader 구조 추출 산출물이 있어야 하는데, 그 산출물은 M3 의 `artifacts/` 에 있고
`.gitignore` 라 서버에 없다. import-linter 가 `server → rulepack` 을 막으므로 여기서
다시 뜰 수도 없다. 기획 14장이 구조 추출을 R3 에 배정했다.

**후보 조회와 승인은 M3 없이 선다.** 후보에 필요한 값(코드·이름·타입·요건·근거)이 M3 의
`config/candidate_rules.json` 에 커밋돼 있고, 근거 대조는 `contracts/find_span.py` 로
직접 뜬다 — `server → contracts` 는 허용 import 다. 자세한 근거는
`services/candidates.py`.

목록은 발행된 팩의 `sources` 에서 만든다. 팩이 정본이고 문서는 그 팩이 인용한 원문이라,
따로 목록을 들고 있으면 둘이 어긋난다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from server.auth import require_token
from server.services import candidates
from server.services.approval_store import AlreadyApproved
from server.services.documents import DocumentNotFound, page_size

router = APIRouter(tags=["documents"])


@router.get("/documents")
def list_documents(request: Request) -> dict[str, list[dict[str, Any]]]:
    """팩이 인용한 규정 원문 목록. 심사위원이 출처를 확인하는 자리다(10.1 6단계).

    `status` 는 파일이 실제로 열리는지로 정한다. 팩에 적혀 있어도 원문이 없으면
    근거 원문 점프(⑭)가 그 문서에서 404 가 되므로, 목록에서 미리 드러내는 편이 낫다.
    """
    runtime = request.app.state.runtime
    docs_dir = request.app.state.settings.docs_dir

    seen: dict[str, dict[str, Any]] = {}
    for row in runtime.pack_store.list(None, False):
        doc = runtime.pack_store.get(row["pack_version"])
        for source in (doc or {}).get("sources", []):
            seen.setdefault(source["doc_id"], source)

    documents = []
    for doc_id, source in sorted(seen.items()):
        try:
            page_size(docs_dir, doc_id, 1)
            status = "ready"
        except DocumentNotFound:
            status = "failed"
        documents.append(
            {
                "doc_id": doc_id,
                "title": source.get("title") or doc_id,
                "publisher": source.get("publisher") or "",
                "url": source.get("url"),
                "snapshot_date": source.get("snapshot_date"),
                "page_count": source.get("page_count"),
                "status": status,
            }
        )
    return {"documents": documents}


@router.get("/documents/{doc_id}/candidates")
def list_candidates(doc_id: str, request: Request) -> dict[str, Any]:
    """항목 후보. 계약: "아직 팩이 아니다. 사람이 승인해야 팩에 들어간다."

    **자동 폐기된 후보를 걸러내지 않는다.** 근거가 원문에 없는 항목은 `span_verified=false`
    에 `status="rejected"` 로 함께 나간다. 기획 8.2 가 S4 화면에 요구하는 "자동 폐기 행
    노출(P4 의 시각 증거)" 이 이 행들이다 — 숨기면 화면이 증거를 못 보여준다.
    """
    settings = request.app.state.settings
    approved = request.app.state.runtime.approvals.by_document(doc_id)
    return candidates.for_document(
        doc_id,
        rules_path=settings.candidate_rules,
        docs_dir=settings.docs_dir,
        approved=approved,
    )


@router.post(
    "/documents/{doc_id}/candidates/{candidate_id}/approve",
    dependencies=[Depends(require_token)],
)
def approve_candidate(
    doc_id: str, candidate_id: str, body: dict[str, Any], request: Request
) -> dict[str, Any]:
    """후보 승인. 계약: "사람이 누른다. **span_verified 가 false 인 후보는 400 으로 거절한다**"

    그 400 이 이 경로의 존재 이유다. 근거가 원문에 없는 항목이 승인을 통과하면 P4 가
    승인 버튼 하나로 뚫린다 — 팩 발행(`/packs/publish`)이 한 번 더 막지만, 막는 자리가
    뒤로 밀릴수록 사람이 이미 승인했다는 기록만 남는다.
    """
    settings = request.app.state.settings
    approved_by = body.get("approved_by")
    if not approved_by:
        raise HTTPException(422, "승인자(approved_by)가 필요합니다.")

    try:
        candidate = candidates.one(
            doc_id,
            candidate_id,
            rules_path=settings.candidate_rules,
            docs_dir=settings.docs_dir,
        )
    except candidates.CandidateNotFound as e:
        raise HTTPException(404, "후보가 없습니다.") from e

    if not candidate["span_verified"]:
        raise HTTPException(400, "근거가 원문에 없어 승인할 수 없습니다.")

    try:
        at = request.app.state.runtime.approvals.approve(
            candidate_id,
            doc_id,
            candidate["suggested_code"],
            approved_by,
            body.get("edits"),
        )
    except AlreadyApproved as e:
        raise HTTPException(409, "이미 승인된 후보입니다.") from e

    return {
        "candidate_id": candidate_id,
        "status": "approved",
        "approved_at": at.isoformat(),
    }
