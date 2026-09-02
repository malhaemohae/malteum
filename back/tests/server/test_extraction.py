"""구조 추출: 오프라인 덤프 → 서버 서빙 (`POST /documents` · `/extraction`).

이 경로의 위험은 **없는 것을 있다고 말하는 것**이다. 추출이 서버에서 돌지 않으므로
상태를 잘못 채우면 검수 화면이 빈 문서를 "추출 완료" 로 그리고, 사람은 원문을 안 열어
본 채 후보를 승인한다. 그래서 `status` 세 값이 각각 언제 나오는지를 여기서 못박는다.

덤프 생성기(`scripts/dump_extraction.py`)의 변환도 같이 본다. 그 결과가 레포에 커밋돼
심사에 그대로 나가므로, 변환이 틀리면 고칠 기회가 한 번뿐이다.
"""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.bootstrap.settings import Settings
from server.main import create_app
from server.services import extraction

_SCRIPTS = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import dump_extraction  # noqa: E402

ASSETS = Path(__file__).resolve().parents[3] / "assets"
EXTRACTION_DIR = ASSETS / "extraction"
TOKEN = "test-admin-token"
SAMPLE_DOC = "05_상품설명서_정기예금"


def _client(tmp_path: Path, **over) -> TestClient:
    settings = Settings(
        event_store="memory",
        admin_token=TOKEN,
        upload_dir=tmp_path / "uploads",
        **over,
    )
    return TestClient(create_app(settings))


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


# --- 덤프가 실제로 계약 모양인지 -------------------------------------------------


def test_committed_dumps_match_the_contract_shape():
    """커밋된 덤프가 계약 enum 밖 값을 들고 있으면 화면이 못 그린다."""
    kinds = {"heading", "paragraph", "list_item", "table", "figure"}
    dumps = sorted(EXTRACTION_DIR.glob("*.json"))
    assert dumps, "덤프가 없다. uv run python scripts/dump_extraction.py"
    for path in dumps:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["doc_id"] == path.stem
        assert payload["status"] == "ready"
        assert payload["page_count"] >= 1
        for block in payload["blocks"]:
            assert block["kind"] in kinds, f"{path.stem}: {block['kind']}"
            assert block["block_id"]
            assert block["page"] >= 1
            if "bbox" in block:
                assert len(block["bbox"]) == 4
            if block["kind"] == "table":
                assert block["table"]["rows"] >= 1
                assert block["table"]["cells"]


def test_tables_keep_their_text():
    """표는 셀에만 글자가 있어 그냥 두면 통째로 사라진다 — 실제로 사라졌던 자리다."""
    payload = json.loads((EXTRACTION_DIR / f"{SAMPLE_DOC}.json").read_text(encoding="utf-8"))
    tables = [b for b in payload["blocks"] if b["kind"] == "table"]
    assert tables, "정기예금 설명서에는 금리표가 있다"
    assert all(t["text"].strip() for t in tables)
    assert any("이자" in t["text"] or "금리" in t["text"] for t in tables)


def test_block_ids_are_unique_per_document():
    for path in sorted(EXTRACTION_DIR.glob("*.json")):
        blocks = json.loads(path.read_text(encoding="utf-8"))["blocks"]
        ids = [b["block_id"] for b in blocks]
        assert len(ids) == len(set(ids)), path.stem


def test_to_blocks_maps_kinds_and_absorbs_table_internals():
    """caption 은 계약 enum 에 없어 paragraph 로 접고, 표 안의 행·셀은 따로 안 뜬다."""
    payload = {
        "kids": [
            {
                "type": "text block",
                "kids": [
                    {
                        "type": "caption",
                        "page number": 1,
                        "content": "표 설명",
                        "bounding box": [1, 2, 3, 4],
                    },
                    {
                        "type": "table",
                        "page number": 1,
                        "number of rows": 1,
                        "number of columns": 2,
                        "rows": [
                            {
                                "row number": 1,
                                "cells": [
                                    {"row number": 1, "column number": 1, "content": "구분"},
                                    {"row number": 1, "column number": 2, "content": "내용"},
                                ],
                            }
                        ],
                    },
                    {"type": "image", "page number": 2, "bounding box": [5, 6, 7, 8]},
                ],
            }
        ]
    }
    blocks = dump_extraction.to_blocks(payload)
    assert [b["kind"] for b in blocks] == ["paragraph", "table", "figure"]
    assert blocks[1]["text"] == "구분 | 내용"
    assert blocks[1]["table"]["cells"][0] == {"r": 1, "c": 1, "text": "구분"}
    assert blocks[0]["bbox"] == [1.0, 2.0, 3.0, 4.0]


@pytest.mark.parametrize(
    ("banner", "major"),
    [
        ('openjdk version "17" 2021-09-14', 17),
        ('java version "1.8.0_202"', 8),
        ('openjdk version "21.0.2" 2024-01-16', 21),
        ("java 를 못 찾음", None),
    ],
)
def test_java_version_is_parsed_not_assumed(banner, major, monkeypatch):
    """PATH 에 java 가 있으면 그냥 쓰는 방식은 이 PC 에서 Java 8 을 물어 jar 가 exit 1 로
    죽었다. 메시지는 "OpenDataLoader 실행 실패" 뿐이라 원인이 안 보였다 (2026-09-02)."""

    class _Proc:
        stderr, stdout = banner, ""

    monkeypatch.setattr(dump_extraction.subprocess, "run", lambda *a, **k: _Proc())
    assert dump_extraction._java_major("java") == major
    assert dump_extraction.MIN_JDK == 17  # 8 은 이 선에 걸려 후보에서 빠진다


# --- 서버가 상태를 어떻게 정하는지 -----------------------------------------------


def test_extraction_serves_the_committed_dump(tmp_path):
    with _client(tmp_path) as client:
        got = client.get(f"/api/documents/{SAMPLE_DOC}/extraction", headers=_auth())
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "ready"
    assert body["doc_id"] == SAMPLE_DOC
    assert len(body["blocks"]) > 10


def test_pdf_without_a_dump_is_extracting_not_ready(tmp_path):
    """덤프만 비워 둔다. PDF 는 그대로다 — 오프라인 한 번이 남은 상태다."""
    with _client(tmp_path, extraction_dir=tmp_path / "none") as client:
        got = client.get(f"/api/documents/{SAMPLE_DOC}/extraction", headers=_auth())
    assert got.status_code == 200
    assert got.json() == {"doc_id": SAMPLE_DOC, "status": "extracting"}


def test_unknown_document_is_404_not_extracting(tmp_path):
    """없는 문서를 extracting 으로 주면 화면이 영원히 도는 스피너를 그린다."""
    with _client(tmp_path, extraction_dir=tmp_path / "none") as client:
        got = client.get("/api/documents/없는문서/extraction", headers=_auth())
    assert got.status_code == 404
    assert got.json()["code"] == "not_found"


def test_broken_dump_is_failed_not_ready(tmp_path):
    bad = tmp_path / "dumps"
    bad.mkdir()
    (bad / f"{SAMPLE_DOC}.json").write_text("{ 깨진", encoding="utf-8")
    with _client(tmp_path, extraction_dir=bad) as client:
        got = client.get(f"/api/documents/{SAMPLE_DOC}/extraction", headers=_auth())
    assert got.json() == {"doc_id": SAMPLE_DOC, "status": "failed"}


@pytest.mark.parametrize("doc_id", ["../secrets", "a/b", "a\\b", ""])
def test_doc_id_cannot_escape_the_directory(doc_id, tmp_path):
    with pytest.raises(extraction.ExtractionNotFound):
        extraction.for_document(doc_id, extraction_dir=tmp_path, pdf_roots=(tmp_path,))


# --- 업로드 ----------------------------------------------------------------------


def _pdf_bytes() -> bytes:
    return (ASSETS / "03_규정문서" / f"{SAMPLE_DOC}.pdf").read_bytes()


def _form(**over) -> dict[str, str]:
    body = {"doc_id": "새문서", "publisher": "금융위원회", "snapshot_date": "2026-08-01"}
    body.update(over)
    return body


def test_upload_stores_the_file_and_reports_extracting(tmp_path):
    with _client(tmp_path, extraction_dir=tmp_path / "none") as client:
        got = client.post(
            "/api/documents",
            files={"file": ("x.pdf", _pdf_bytes(), "application/pdf")},
            data=_form(),
            headers=_auth(),
        )
        assert got.status_code == 202
        assert got.json()["status"] == "extracting"
        assert got.json()["doc_id"] == "새문서"

        # 목록에 뜨고, 추출은 아직이라 extracting 이다
        listed = {d["doc_id"]: d for d in client.get("/api/documents").json()["documents"]}
        assert listed["새문서"]["status"] == "extracting"
        assert listed["새문서"]["publisher"] == "금융위원회"

        again = client.get("/api/documents/새문서/extraction", headers=_auth())
        assert again.json() == {"doc_id": "새문서", "status": "extracting"}

    assert (tmp_path / "uploads" / "documents" / "새문서.pdf").is_file()


def test_upload_rejects_a_file_that_is_not_a_pdf(tmp_path):
    with _client(tmp_path) as client:
        got = client.post(
            "/api/documents",
            files={"file": ("x.pdf", b"not a pdf", "application/pdf")},
            data=_form(),
            headers=_auth(),
        )
    assert got.status_code == 422
    assert got.json()["code"] == "validation_failed"
    # 못 쓸 파일을 남기지 않는다
    assert not (tmp_path / "uploads" / "documents" / "새문서.pdf").exists()


@pytest.mark.parametrize(
    "over",
    [{"snapshot_date": "2026/08/01"}, {"publisher": " "}, {"doc_id": "../탈출"}],
    ids=["날짜형식", "발행처없음", "경로탈출"],
)
def test_upload_rejects_bad_metadata(over, tmp_path):
    with _client(tmp_path) as client:
        got = client.post(
            "/api/documents",
            files={"file": ("x.pdf", _pdf_bytes(), "application/pdf")},
            data=_form(**over),
            headers=_auth(),
        )
    assert got.status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/api/documents"), ("get", f"/api/documents/{SAMPLE_DOC}/extraction")],
)
def test_write_paths_need_a_token(method, path, tmp_path):
    """계약 securitySchemes 가 이 둘을 토큰 경로로 지정했다."""
    with _client(tmp_path) as client:
        got = getattr(client, method)(path)
    assert got.status_code == 401
