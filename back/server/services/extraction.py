"""구조 추출 결과를 읽어 준다. **서버는 추출을 실행하지 않는다.**

추출기(OpenDataLoader)는 JDK 17 을 부르는 자바 프로그램이다. 배포 이미지에 JRE 를 넣으면
200MB 가 따라다니고, 심사 기간(9/7~9/11)에 그 프로세스가 죽으면 검수 화면이 통째로 빈다.
그래서 추출은 `scripts/dump_extraction.py` 로 **오프라인에서 미리 떠서 커밋**하고 여기서는
읽기만 한다. 덤프는 이미 계약 모양이라 여기서 변환하지 않는다 — 변환이 두 곳에 있으면
한쪽만 고쳐진다.

`status` 세 값의 뜻(계약 enum):

    ready       덤프가 있다. `blocks` 가 따라간다
    extracting  PDF 는 있는데 덤프가 아직 없다. 오프라인 한 번을 더 돌리면 ready 가 된다
    failed      덤프가 있는데 읽히지 않는다 (깨진 파일)

PDF 도 덤프도 없으면 404 다. **없는 문서를 `extracting` 으로 돌려주지 않는다** — 검수
화면이 영원히 도는 스피너를 그리고, 그 사이 사람은 추출이 진행 중이라고 믿는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ExtractionNotFound(LookupError):
    pass


def _safe(doc_id: str) -> str:
    # doc_id 는 URL 로 들어온다. 경로가 되지 않게 막는다 (services/documents.py 와 같은 규약)
    if not doc_id or "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        raise ExtractionNotFound(doc_id)
    return doc_id


def _pdf_exists(roots: tuple[Path, ...], doc_id: str) -> bool:
    return any((root / f"{doc_id}.pdf").is_file() for root in roots if root.is_dir())


def for_document(
    doc_id: str, *, extraction_dir: Path, pdf_roots: tuple[Path, ...]
) -> dict[str, Any]:
    """계약 `/documents/{doc_id}/extraction` 의 200 본문."""
    doc_id = _safe(doc_id)
    dump = extraction_dir / f"{doc_id}.json"

    if not dump.is_file():
        if _pdf_exists(pdf_roots, doc_id):
            return {"doc_id": doc_id, "status": "extracting"}
        raise ExtractionNotFound(doc_id)

    try:
        payload = json.loads(dump.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # 덤프가 깨졌다. 빈 blocks 로 ready 를 주면 검수 화면이 "추출됐는데 내용이 없는
        # 문서" 로 읽어 사람이 원문을 안 열어 본다. 실패는 실패로 보여야 한다
        return {"doc_id": doc_id, "status": "failed"}

    payload["doc_id"] = doc_id  # 파일 이름이 정본. 덤프 안 값이 어긋나면 이쪽을 믿는다
    payload.setdefault("status", "ready")
    return payload


def has_dump(doc_id: str, extraction_dir: Path) -> bool:
    try:
        return (extraction_dir / f"{_safe(doc_id)}.json").is_file()
    except ExtractionNotFound:
        return False
