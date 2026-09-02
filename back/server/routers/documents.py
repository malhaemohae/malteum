"""규정 원문 문서. 목록 · 업로드 · 추출 결과 · 후보 조회 · 후보 승인.

**추출은 서버에서 돌지 않는다.** OpenDataLoader 는 JDK 17 을 부르는 자바 프로그램이라
배포 이미지에 넣지 않았다. `scripts/dump_extraction.py` 로 오프라인에서 미리 떠서
`assets/extraction/` 에 커밋하고, 여기서는 그 파일을 읽기만 한다. 그래서 업로드 직후는
계약대로 `extracting` 이고 오프라인 한 번이 지나면 `ready` 가 된다. 자세한 근거는
`services/extraction.py`.

**후보 조회와 승인은 M3 없이 선다.** 후보에 필요한 값(코드·이름·타입·요건·근거)이 M3 의
`config/candidate_rules.json` 에 커밋돼 있고, 근거 대조는 `contracts/find_span.py` 로
직접 뜬다 — `server → contracts` 는 허용 import 다. 자세한 근거는
`services/candidates.py`.

목록은 발행된 팩의 `sources` 에서 만든다. 팩이 정본이고 문서는 그 팩이 인용한 원문이라,
따로 목록을 들고 있으면 둘이 어긋난다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile

from server.auth import require_token
from server.services import candidates, doc_intake, extraction
from server.services.documents import DocumentNotFound, page_size

router = APIRouter(tags=["documents"])


@router.get("/documents")
def list_documents(request: Request) -> dict[str, list[dict[str, Any]]]:
    """팩이 인용한 규정 원문 + 업로드된 원문. 심사위원이 출처를 확인하는 자리다(10.1 6단계).

    `status` 는 추출까지 보고 정한다. 원문이 안 열리면 `failed` — 팩에 적혀 있어도 파일이
    없으면 근거 원문 점프(⑭)가 그 문서에서 404 가 되므로 목록에서 미리 드러낸다. 열리는데
    추출 덤프가 없으면 `extracting` 이다. `/extraction` 이 같은 규칙으로 답하므로 목록과
    상세가 어긋나지 않는다.
    """
    runtime = request.app.state.runtime
    settings = request.app.state.settings
    docs_dir = settings.docs_dir
    upload_root = Path(settings.upload_dir) / "documents"

    seen: dict[str, dict[str, Any]] = {}
    for row in runtime.pack_store.list(None, False):
        doc = runtime.pack_store.get(row["pack_version"])
        for source in (doc or {}).get("sources", []):
            seen.setdefault(source["doc_id"], source)
    # 업로드된 문서는 아직 어느 팩에도 없다. 팩 문서를 덮지 않게 뒤에 채운다
    for meta in doc_intake.uploaded(upload_root):
        seen.setdefault(meta["doc_id"], meta)

    documents = []
    for doc_id, source in sorted(seen.items()):
        documents.append(
            {
                "doc_id": doc_id,
                "title": source.get("title") or doc_id,
                "publisher": source.get("publisher") or "",
                "url": source.get("url"),
                "snapshot_date": source.get("snapshot_date"),
                "page_count": source.get("page_count"),
                "status": _status(doc_id, docs_dir, upload_root, settings.extraction_dir),
            }
        )
    return {"documents": documents}


def _status(doc_id: str, docs_dir: Path, upload_root: Path, extraction_dir: Path) -> str:
    for root in (docs_dir, upload_root):
        try:
            page_size(root, doc_id, 1)
        except DocumentNotFound:
            continue
        return "ready" if extraction.has_dump(doc_id, extraction_dir) else "extracting"
    return "failed"


@router.post("/documents", status_code=202, dependencies=[Depends(require_token)])
async def upload_document(
    request: Request,
    file: UploadFile,
    doc_id: str = Form(...),
    publisher: str = Form(...),
    snapshot_date: str = Form(...),
    title: str | None = Form(None),
    url: str | None = Form(None),
) -> dict[str, Any]:
    """원문 업로드. 계약: "OpenDataLoader 로 구조를 뜨고 pypdfium2 로 페이지 좌표를 잡는다."

    **여기서는 저장과 검사까지다.** 구조 추출은 오프라인(`scripts/dump_extraction.py`)이라
    응답은 계약대로 `extracting` 이고, 그 스크립트가 한 번 돌면 `ready` 가 된다. 자바를
    배포 이미지에 넣지 않은 이유는 `services/extraction.py`.
    """
    settings = request.app.state.settings
    try:
        meta = doc_intake.store(
            Path(settings.upload_dir) / "documents",
            doc_id,
            await file.read(),
            publisher=publisher,
            snapshot_date=snapshot_date,
            title=title,
            url=url,
        )
    except doc_intake.IntakeError as e:
        raise HTTPException(422, str(e)) from e
    return {"doc_id": meta["doc_id"], "status": "extracting", "page_count": meta["page_count"]}


@router.get("/documents/{doc_id}/extraction", dependencies=[Depends(require_token)])
def get_extraction(doc_id: str, request: Request) -> dict[str, Any]:
    """구조 추출 결과. 계약: "검수 화면의 입력. 표는 셀 단위로 구조를 채워 준다."

    덤프를 그대로 준다. 덤프가 이미 계약 모양이라(`scripts/dump_extraction.py`) 여기서
    다시 변환하지 않는다 — 변환이 두 곳에 있으면 한쪽만 고쳐진다.
    """
    settings = request.app.state.settings
    try:
        return extraction.for_document(
            doc_id,
            extraction_dir=settings.extraction_dir,
            pdf_roots=(settings.docs_dir, Path(settings.upload_dir) / "documents"),
        )
    except extraction.ExtractionNotFound as e:
        raise HTTPException(404, "문서가 없습니다.") from e


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

    # 이미 승인돼 있으면 첫 기록의 시각이 그대로 온다(멱등). 계약이 이 경로에 200 과
    # 400 만 두어서 409 를 낼 자리가 없다 — 덮어쓰지는 않는다(approval_store.py)
    at = request.app.state.runtime.approvals.approve(
        candidate_id,
        doc_id,
        candidate["suggested_code"],
        approved_by,
        body.get("edits"),
    )
    return {
        "candidate_id": candidate_id,
        "status": "approved",
        "approved_at": at.isoformat(),
    }
