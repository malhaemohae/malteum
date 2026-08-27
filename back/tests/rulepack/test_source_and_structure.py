from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rulepack.source_manifest import ManifestError, build_run_manifest
from rulepack.structure import build_chunks_from_structure, extract_documents

REPO_ROOT = Path(__file__).resolve().parents[3]

from rulepack import paths  # noqa: E402


def test_run_manifest_fixes_all_seven_sources_and_parser_identity() -> None:
    run = build_run_manifest(REPO_ROOT)

    assert run.parser.name == "opendataloader-pdf"
    assert run.parser.version == "2.3.0"
    assert len(run.sources) == 7
    assert sum(source.page_count for source in run.sources) == 120

    for source in run.sources:
        expected = hashlib.sha256(source.path.read_bytes()).hexdigest()
        assert source.sha256 == expected
        assert source.snapshot_date == "2026-08-23"
        assert source.path.parent == paths.docs_dir(REPO_ROOT)
        assert source.path.name == f"{source.doc_id}.pdf"


def test_manifest_rejects_a_source_path_outside_regulation_directory(tmp_path: Path) -> None:
    escaped = tmp_path / "outside.pdf"
    escaped.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(ManifestError, match="원천 디렉터리 밖"):
        build_run_manifest(REPO_ROOT, source_override={"01_금융소비자보호법": escaped})


def test_real_structure_preserves_legal_lists_and_wide_loan_table(tmp_path: Path) -> None:
    run = build_run_manifest(REPO_ROOT)
    wanted = {
        "01_금융소비자보호법",
        "06_상품설명서_가계대출",
    }
    sources = [source for source in run.sources if source.doc_id in wanted]

    documents = extract_documents(sources, tmp_path)
    by_id = {document.doc_id: document for document in documents}

    law_chunks = build_chunks_from_structure(by_id["01_금융소비자보호법"])
    loan_chunks = build_chunks_from_structure(by_id["06_상품설명서_가계대출"])

    assert any(chunk.kind == "list_item" and "제19조" in chunk.text for chunk in law_chunks)
    wide_tables = [chunk for chunk in loan_chunks if chunk.kind == "table" and chunk.table]
    assert any(table.table.column_count >= 10 for table in wide_tables)
    assert any(
        cell.row_span > 1 or cell.column_span > 1
        for table in wide_tables
        for row in table.table.rows
        for cell in row.cells
    )


def test_structure_rejects_oversized_pdf_before_parser_call(tmp_path: Path) -> None:
    run = build_run_manifest(REPO_ROOT)
    source = run.sources[0]

    with pytest.raises(ManifestError, match="크기 제한"):
        extract_documents([source], tmp_path, max_file_bytes=1)
