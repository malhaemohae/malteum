from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rulepack.source_manifest import ManifestError, build_run_manifest
from rulepack.structure import build_chunks_from_structure, extract_documents

REPO_ROOT = Path(__file__).resolve().parents[3]

from rulepack import paths  # noqa: E402


def test_run_manifest_fixes_all_eight_sources_and_parser_identity() -> None:
    run = build_run_manifest(REPO_ROOT)

    assert run.parser.name == "opendataloader-pdf"
    assert run.parser.version == "2.3.0"
    assert len(run.sources) == 8
    # 06 가계대출 설명서를 2025.01 개정본(24쪽)으로 교체하며 26 -> 24 로,
    # 05 정기예금 설명서를 현행본(4쪽)으로 교체하며 7 -> 4 로 줄었다.
    # 08 BEST 신용대출 상품 공시 스냅샷(3쪽)이 2026-09-05 에 더해져 115 -> 118
    assert sum(source.page_count for source in run.sources) == 118

    for source in run.sources:
        expected = hashlib.sha256(source.path.read_bytes()).hexdigest()
        assert source.sha256 == expected
        assert source.path.parent == paths.docs_dir(REPO_ROOT)
        assert source.path.name == f"{source.doc_id}.pdf"

    # 웹 스냅샷 원천만 자기 행의 날짜를 쓰고, 나머지는 수집 확인 일자를 쓴다
    by_id = {source.doc_id: source.snapshot_date for source in run.sources}
    assert by_id.pop("08_상품공시_BEST신용대출") == "2026-09-05"
    assert set(by_id.values()) == {"2026-08-23"}


def _row(filename: str, status: str = "확보") -> str:
    link = "[제목](https://example.com/a.pdf)"
    return f"| `{filename}` | 법령 | 법제처 | {link} | 1p / 1자 | {status} | 근거 |"


def _synthetic_docs(tmp_path: Path, rows: list[str], pdfs: list[str]) -> Path:
    """표와 폴더만 있는 최소 배치. 표·폴더 대조는 PDF 를 열기 전에 끝나므로 빈 파일로 충분하다."""
    root = tmp_path / "repo"
    docs = root / "assets" / "03_규정문서"
    docs.mkdir(parents=True)
    header = (
        "수집 확인 2026-08-23\n\n"
        "| 파일 | 분류 | 발행 기관 | 문서 | 규모 | 상태 | 무엇의 근거 |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
    )
    (docs / "MANIFEST.md").write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    for name in pdfs:
        (docs / name).write_bytes(b"")
    return root


def test_manifest_rejects_pdf_missing_from_table_or_folder(tmp_path: Path) -> None:
    """표와 폴더가 어긋나면 어느 쪽이 빠졌는지 말하고 멈춘다.

    옛 코드는 행 개수를 7 로 박아 두었다. 그러면 원천을 늘릴 때 코드를 고쳐야 하고,
    표에 없는 PDF 는 조용히 원천에서 빠진다 (2026-09-05).
    """
    from rulepack import source_manifest

    root = _synthetic_docs(tmp_path, [_row("01_x.pdf")], ["01_x.pdf", "99_표에_없는_문서.pdf"])
    with pytest.raises(source_manifest.ManifestError, match="폴더에만.*99_표에_없는_문서"):
        build_run_manifest(root)

    (root / "assets" / "03_규정문서" / "99_표에_없는_문서.pdf").unlink()
    (root / "assets" / "03_규정문서" / "01_x.pdf").unlink()
    with pytest.raises(source_manifest.ManifestError, match="표에만.*01_x"):
        build_run_manifest(root)


def test_manifest_rejects_duplicate_row_and_empty_table(tmp_path: Path) -> None:
    """같은 PDF 가 두 행이면 팩 `sources` 에 두 번 실리므로 집합 비교와 따로 잡는다.

    옛 행 개수 상수가 우연히 막아 주던 것이라, 집합 비교로 바꾸면서 명시 검사로 남겼다.
    """
    from rulepack import source_manifest

    root = _synthetic_docs(tmp_path, [_row("01_x.pdf"), _row("01_x.pdf")], ["01_x.pdf"])
    with pytest.raises(source_manifest.ManifestError, match="두 번.*01_x"):
        build_run_manifest(root)

    root = _synthetic_docs(tmp_path / "empty", [], ["01_x.pdf"])
    with pytest.raises(source_manifest.ManifestError, match="PDF 행이 없음"):
        build_run_manifest(root)


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


def test_find_repo_root_skips_back_dir(tmp_path: Path) -> None:
    """팀 레포 배치에서 back/ 이 아니라 그 위를 루트로 잡는다.

    back/contracts 가 있어 계약 폴더만 보면 back/ 이 먼저 걸린다. 그러면
    규정 원천을 back/assets 에서 찾다 LayoutError 로 죽는다 (2026-08-29).
    """
    root = tmp_path / "repo"
    (root / "back" / "contracts").mkdir(parents=True)
    (root / "back" / "rulepack").mkdir(parents=True)
    (root / "assets" / "03_규정문서").mkdir(parents=True)
    assert paths.find_repo_root(root / "back" / "rulepack") == root


def test_find_repo_root_personal_layout(tmp_path: Path) -> None:
    """개인 작업장 배치도 그대로 잡힌다."""
    root = tmp_path / "work"
    (root / "contracts").mkdir(parents=True)
    (root / "rulepack" / "src").mkdir(parents=True)
    (root / "03_규정문서").mkdir(parents=True)
    assert paths.find_repo_root(root / "rulepack" / "src") == root


def test_find_repo_root_raises_when_sources_missing(tmp_path: Path) -> None:
    """계약만 있고 규정 원천이 없으면 루트로 인정하지 않는다."""
    root = tmp_path / "half"
    (root / "back" / "contracts").mkdir(parents=True)
    with pytest.raises(paths.LayoutError):
        paths.find_repo_root(root / "back" / "contracts")


def test_repo_root_matches_cli_default() -> None:
    """CLI 기본값이 테스트가 쓰는 루트와 같아야 한다.

    테스트는 parents[3] 하드코딩, CLI 는 find_repo_root() 를 쓴다. 둘이
    갈라지면 테스트는 통과하는데 CLI 만 죽는다. 실제로 그랬다 (2026-08-29).
    """
    assert paths.find_repo_root() == REPO_ROOT


def test_publisher_comes_from_manifest_not_code() -> None:
    """발행 기관은 MANIFEST 표에서 읽어야 한다.

    코드에 매핑을 두면 원천을 늘릴 때마다 코드를 같이 고쳐야 하고, 표와 코드가
    어긋나도 아무도 모른다. 실제로 표준약관 2건이 그랬다. 코드는 게시한 은행을
    적고 있었는데(한국씨티은행·우리은행) 실제 발행 기관은 은행연합회다
    (2026-08-30).
    """
    run = build_run_manifest(REPO_ROOT)
    by_id = {s.doc_id: s.publisher for s in run.sources}

    assert by_id["03_예금거래기본약관"].startswith("은행연합회")
    assert by_id["04_은행여신거래기본약관_가계용"].startswith("은행연합회")
    assert by_id["01_금융소비자보호법"] == "법제처"

    # 표에 적힌 값이 그대로 와야 한다. 코드 어디에도 기관명을 박아 두지 않는다.
    manifest = (paths.docs_dir(REPO_ROOT) / "MANIFEST.md").read_text(encoding="utf-8")
    for doc_id, publisher in by_id.items():
        assert publisher in manifest, f"{doc_id}: MANIFEST 에 없는 발행 기관 {publisher}"


def test_manifest_row_needs_publisher_column() -> None:
    """발행 기관 열이 빠진 행은 원천으로 인정하지 않는다.

    열이 사라지면 조용히 다른 칸을 발행 기관으로 읽는 것보다, 그 행을 못 읽어
    개수가 안 맞는 편이 낫다.
    """
    from rulepack.source_manifest import _ROW_RE

    없는_행 = "| `01_x.pdf` | 법령 | [제목](https://example.com/a.pdf) | 31p / 100자 | 확보 |"
    assert _ROW_RE.search(없는_행) is None

    있는_행 = (
        "| `01_x.pdf` | 법령 | 법제처 | [제목](https://example.com/a.pdf) | 31p / 100자 | 확보 |"
    )
    match = _ROW_RE.search(있는_행)
    assert match is not None
    assert match.group("publisher") == "법제처"
