"""규정 원문 업로드. 받아서 **검사하고 저장만** 한다.

추출은 여기서 돌지 않는다. 이유는 `services/extraction.py` 에 적어 두었다 — 추출기가
자바라서 배포 이미지에 넣지 않았고, `scripts/dump_extraction.py` 로 오프라인에서 뜬다.
그래서 업로드 직후 상태는 계약 그대로 `extracting` 이고, 오프라인 한 번이 지나면
`ready` 가 된다. **거짓으로 ready 를 주지 않는다** — 검수 화면이 빈 문서를 "추출 완료"
로 그리면 사람이 원문을 안 열어 본다.

PDF 를 여는 것까지가 검사다. 못 여는 파일을 받아 두면 `/documents` 목록에는 뜨는데
페이지 렌더(⑭)에서 404 가 나고, 그 사실이 시연 중에야 드러난다.

메타데이터(`title`·`publisher`·`url`·`snapshot_date`)는 PDF 옆에 `.meta.json` 으로 둔다.
팩에 실린 문서는 팩의 `sources` 가 정본이지만, 업로드된 문서는 아직 어느 팩에도 없어
출처를 적어 둘 자리가 여기밖에 없다.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

META_SUFFIX = ".meta.json"
MAX_BYTES = 25 * 1024 * 1024  # rulepack/structure.py 의 추출 상한과 같은 값


class IntakeError(ValueError):
    pass


def _safe(doc_id: str) -> str:
    if not doc_id or "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        raise IntakeError("doc_id 에 경로 문자를 쓸 수 없습니다.")
    if len(doc_id) > 120:
        raise IntakeError("doc_id 가 너무 깁니다(120자).")
    return doc_id


def store(
    upload_root: Path,
    doc_id: str,
    content: bytes,
    *,
    publisher: str,
    snapshot_date: str,
    title: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    """PDF 와 메타를 저장하고 페이지 수를 돌려준다. 실패하면 아무것도 남기지 않는다."""
    doc_id = _safe(doc_id)
    if not content:
        raise IntakeError("빈 파일입니다.")
    if len(content) > MAX_BYTES:
        raise IntakeError(f"파일이 너무 큽니다({len(content) // 1024 // 1024}MB, 상한 25MB).")
    if not publisher.strip():
        raise IntakeError("publisher 가 필요합니다.")
    try:
        date.fromisoformat(snapshot_date)
    except ValueError as e:
        raise IntakeError(f"snapshot_date 는 YYYY-MM-DD 여야 합니다: {snapshot_date}") from e

    upload_root.mkdir(parents=True, exist_ok=True)
    target = upload_root / f"{doc_id}.pdf"
    target.write_bytes(content)
    try:
        page_count = _page_count(target)
    except Exception as e:
        target.unlink(missing_ok=True)  # 못 쓸 파일을 남기지 않는다
        raise IntakeError(f"PDF 를 열 수 없습니다: {e}") from e

    meta = {
        "doc_id": doc_id,
        "title": title or doc_id,
        "publisher": publisher,
        "url": url,
        "snapshot_date": snapshot_date,
        "page_count": page_count,
    }
    (upload_root / f"{doc_id}{META_SUFFIX}").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return meta


def _page_count(path: Path) -> int:
    pdf = pdfium.PdfDocument(str(path))
    try:
        count = len(pdf)
    finally:
        pdf.close()
    if count < 1:
        raise IntakeError("빈 PDF 입니다.")
    return count


def uploaded(upload_root: Path) -> list[dict[str, Any]]:
    """업로드된 문서의 메타. 목록(`GET /documents`)이 팩 문서 뒤에 이어 붙인다."""
    if not upload_root.is_dir():
        return []
    out = []
    for meta_path in sorted(upload_root.glob(f"*{META_SUFFIX}")):
        try:
            out.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue  # 깨진 메타 하나가 목록 전체를 막지 않게 한다
    return out
