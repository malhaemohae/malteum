"""규정 원문 문서. 목록과 페이지 렌더만 여기 있다.

**업로드·추출·후보 승인은 없다.** 그 넷은 OpenDataLoader 구조 추출 → LLM 항목 추출 →
근거 스팬 대조 → 좌표 부여로 이어지는 M3 파이프라인이고, import-linter 가
`server → rulepack` 을 막는다(`pyproject.toml`). 표면만 여기 두고 알맹이는 못 부른다.
누가 어떻게 이을지는 아직 안 정해졌다 — 17장 경계 표에 M1↔M3 행이 없다.

목록은 발행된 팩의 `sources` 에서 만든다. 팩이 정본이고 문서는 그 팩이 인용한 원문이라,
따로 목록을 들고 있으면 둘이 어긋난다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

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
