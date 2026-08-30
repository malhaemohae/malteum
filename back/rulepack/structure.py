from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import opendataloader_pdf
import pypdfium2 as pdfium

from .source_manifest import ManifestError, SourceRecord


def _ensure_java_on_path() -> None:
    """OpenDataLoader 는 java 를 부른다. PATH 에 없으면 관례 위치를 찾아 붙인다.

    JAVA_HOME 없는 셸에서 WinError 2 로 죽는 함정이 실제로 있었다 (2026-08-27).
    탐색 순서: 이미 PATH 에 있으면 그대로 → JAVA_HOME → install-jdk 기본 위치(~/.jdk).
    """
    if shutil.which("java"):
        return
    candidates: list[Path] = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]))
    jdk_root = Path.home() / ".jdk"
    if jdk_root.is_dir():
        candidates.extend(sorted(jdk_root.iterdir(), reverse=True))
    for home in candidates:
        java = home / "bin" / ("java.exe" if os.name == "nt" else "java")
        if java.is_file():
            os.environ["JAVA_HOME"] = str(home)
            os.environ["PATH"] = str(home / "bin") + os.pathsep + os.environ.get("PATH", "")
            return
    raise ManifestError(
        "java 를 찾지 못함. JDK 17 이상을 설치하거나 JAVA_HOME 을 설정하라. "
        "빠른 설치: pip install install-jdk 후 python -c \"import jdk; jdk.install('21')\""
    )


@dataclass(frozen=True)
class TableCell:
    row_number: int
    column_number: int
    row_span: int
    column_span: int
    text: str


@dataclass(frozen=True)
class TableRow:
    row_number: int
    cells: tuple[TableCell, ...]


@dataclass(frozen=True)
class TableData:
    row_count: int
    column_count: int
    rows: tuple[TableRow, ...]


@dataclass(frozen=True)
class StructureChunk:
    doc_id: str
    page: int
    kind: str
    structure_path: tuple[str, ...]
    text: str
    table: TableData | None = None


@dataclass(frozen=True)
class StructuredDocument:
    doc_id: str
    source: SourceRecord
    payload: dict[str, Any]


def _page_has_text(source: SourceRecord) -> bool:
    document = pdfium.PdfDocument(source.path)
    try:
        for page in document:
            text_page = page.get_textpage()
            if text_page.get_text_bounded().strip():
                return True
    finally:
        document.close()
    return False


def extract_documents(
    sources: Iterable[SourceRecord],
    output_dir: Path,
    *,
    max_file_bytes: int = 25 * 1024 * 1024,
) -> list[StructuredDocument]:
    selected = list(sources)
    if not selected:
        return []

    for source in selected:
        if source.path.stat().st_size > max_file_bytes:
            raise ManifestError(f"PDF 크기 제한 초과: {source.doc_id}")
        if source.page_count < 1:
            raise ManifestError(f"빈 PDF 거부: {source.doc_id}")
        if not _page_has_text(source):
            raise ManifestError(f"스캔 PDF 또는 텍스트 없는 PDF: {source.doc_id}")

    output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_java_on_path()
    try:
        opendataloader_pdf.convert(
            input_path=[str(source.path) for source in selected],
            output_dir=str(output_dir),
            format="json",
            quiet=True,
        )
    except Exception as exc:
        raise ManifestError(f"OpenDataLoader 실행 실패: {exc}") from exc

    documents: list[StructuredDocument] = []
    for source in selected:
        output_path = output_dir / f"{source.doc_id}.json"
        if not output_path.is_file():
            raise ManifestError(f"OpenDataLoader 출력 없음: {output_path.name}")
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        if payload.get("number of pages") != source.page_count:
            raise ManifestError(f"구조 출력 page_count 불일치: {source.doc_id}")
        documents.append(StructuredDocument(source.doc_id, source, payload))
    return documents


def _text_of(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    own = node.get("content")
    if isinstance(own, str) and own.strip():
        return own.strip()
    parts: list[str] = []
    for key in ("kids", "list items"):
        for child in node.get(key, []):
            text = _text_of(child)
            if text:
                parts.append(text)
    return " ".join(parts).strip()


def _table_of(node: dict[str, Any]) -> TableData:
    rows: list[TableRow] = []
    for raw_row in node.get("rows", []):
        cells = tuple(
            TableCell(
                row_number=int(cell["row number"]),
                column_number=int(cell["column number"]),
                row_span=int(cell["row span"]),
                column_span=int(cell["column span"]),
                text=_text_of(cell),
            )
            for cell in raw_row.get("cells", [])
        )
        rows.append(TableRow(int(raw_row["row number"]), cells))
    return TableData(
        row_count=int(node["number of rows"]),
        column_count=int(node["number of columns"]),
        rows=tuple(rows),
    )


def build_chunks_from_structure(document: StructuredDocument) -> list[StructureChunk]:
    chunks: list[StructureChunk] = []

    def visit(node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, path + (str(index),))
            return
        if not isinstance(node, dict):
            return

        kind = node.get("type")
        page = node.get("page number")
        label = str(kind or "node")
        current_path = path + (label,)
        if kind == "table" and isinstance(page, int):
            table = _table_of(node)
            row_text = [" | ".join(cell.text for cell in row.cells) for row in table.rows]
            chunks.append(
                StructureChunk(
                    document.doc_id,
                    page,
                    "table",
                    current_path,
                    "\n".join(row_text),
                    table,
                )
            )
            return
        if kind in {"heading", "paragraph", "list item", "caption"} and isinstance(page, int):
            text = _text_of(node)
            if text:
                chunks.append(
                    StructureChunk(
                        document.doc_id,
                        page,
                        "list_item" if kind == "list item" else str(kind),
                        current_path,
                        text,
                    )
                )

        for key in ("kids", "list items"):
            visit(node.get(key, []), current_path + (key,))

    visit(document.payload.get("kids", []), (document.doc_id,))
    return chunks
