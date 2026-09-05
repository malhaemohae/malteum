from __future__ import annotations

import hashlib
import importlib.metadata
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from . import paths


class ManifestError(ValueError):
    """원천 manifest 또는 PDF가 안전 계약을 어겼음을 나타냄."""


@dataclass(frozen=True)
class ParserIdentity:
    name: str
    version: str


@dataclass(frozen=True)
class SourceRecord:
    doc_id: str
    title: str
    publisher: str
    url: str
    snapshot_date: str
    page_count: int
    sha256: str
    path: Path


@dataclass(frozen=True)
class RunManifest:
    parser: ParserIdentity
    sources: tuple[SourceRecord, ...]


_SNAPSHOT_RE = re.compile(r"수집 확인\s+(\d{4}-\d{2}-\d{2})")
# MANIFEST 표: | 파일 | 분류 | 발행 기관 | 문서(링크) | 규모 | 상태 | 무엇의 근거 |
# 발행 기관을 표에서 읽는다. 코드에 매핑을 두면 원천을 늘릴 때마다 코드를 같이
# 고쳐야 하고, 표와 코드가 어긋나도 아무도 모른다 (2026-08-30).
_ROW_RE = re.compile(
    r"^\|\s*`(?P<filename>[^`]+\.pdf)`\s*\|[^|]*\|\s*(?P<publisher>[^|]+?)\s*\|\s*"
    r"\[(?P<title>[^]]+)]\((?P<url>https?://.+)\)\s*\|\s*"
    r"(?P<pages>\d+)p\s*/[^|]*\|\s*(?P<status>[^|]*)\|",
    re.MULTILINE,
)
# 행 단위 스냅샷 일자. 상태 칸에 `스냅샷 YYYY-MM-DD` 가 있으면 그 원천만 그 날짜를 쓴다.
# 웹페이지를 PDF 로 인쇄한 원천(08)은 다른 PDF 와 수집 시점이 달라 하나의 날짜로는
# 거짓이 된다 (2026-09-05). 상태 칸만 보므로 '무엇의 근거' 칸에 적힌 날짜는 건드리지 않는다.
_ROW_SNAPSHOT_RE = re.compile(r"스냅샷\s+(\d{4}-\d{2}-\d{2})")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def build_run_manifest(
    repo_root: Path,
    *,
    source_override: Mapping[str, Path] | None = None,
) -> RunManifest:
    root = repo_root.resolve()
    docs_dir = paths.docs_dir(root).resolve()
    manifest_path = docs_dir / "MANIFEST.md"
    text = manifest_path.read_text(encoding="utf-8")

    snapshot_match = _SNAPSHOT_RE.search(text)
    if not snapshot_match:
        raise ManifestError("MANIFEST에서 snapshot_date를 찾지 못함")
    snapshot_date = snapshot_match.group(1)

    rows = list(_ROW_RE.finditer(text))
    if not rows:
        raise ManifestError(
            "MANIFEST 에 PDF 행이 없음. "
            "행이 표 규격(파일·분류·기관·문서·규모·상태)과 다르면 여기에 잡힘"
        )
    # 표와 폴더가 서로를 빠짐없이, 한 번씩 가리켜야 한다. 개수를 상수로 박아 두면 원천을
    # 늘릴 때마다 코드를 고쳐야 하고, 표에서 빠진 PDF 는 조용히 원천에서 사라진다.
    # 같은 파일이 두 행이면 팩 `sources` 에 두 번 실리므로 집합 비교와 따로 잡는다.
    filenames = [row.group("filename") for row in rows]
    listed = set(filenames)
    if len(listed) != len(filenames):
        dupes = sorted({name for name in filenames if filenames.count(name) > 1})
        raise ManifestError(f"MANIFEST 에 같은 PDF 행이 두 번: {dupes}")
    on_disk = {path.name for path in docs_dir.glob("*.pdf")}
    if listed != on_disk:
        raise ManifestError(
            "MANIFEST PDF 행과 폴더의 PDF 가 다름: "
            f"표에만 {sorted(listed - on_disk)}, 폴더에만 {sorted(on_disk - listed)}. "
            "폴더에만 있는 파일은 행이 없거나 행이 표 규격과 다른 것"
        )

    overrides = dict(source_override or {})
    sources: list[SourceRecord] = []
    for row in rows:
        filename = row.group("filename")
        doc_id = Path(filename).stem
        candidate = Path(overrides.get(doc_id, docs_dir / filename)).resolve()
        if not _is_within(candidate, docs_dir):
            raise ManifestError(f"원천 디렉터리 밖 경로 거부: {candidate}")
        if not candidate.is_file():
            raise ManifestError(f"원천 PDF 없음: {candidate}")

        # 한 번 읽은 바이트로 쪽수와 해시를 모두 낸다. 해시는 이 바이트의 것이어야 한다.
        data = candidate.read_bytes()
        try:
            pdf = pdfium.PdfDocument(data)
        except Exception as exc:
            raise ManifestError(f"PDF 열기 실패: {filename}: {exc}") from exc
        try:
            actual_pages = len(pdf)
        finally:
            pdf.close()
        declared_pages = int(row.group("pages"))
        if actual_pages != declared_pages:
            raise ManifestError(
                f"page_count 불일치: {filename}: MANIFEST={declared_pages}, PDF={actual_pages}"
            )

        row_snapshot = _ROW_SNAPSHOT_RE.search(row.group("status"))
        sources.append(
            SourceRecord(
                doc_id=doc_id,
                title=row.group("title"),
                publisher=row.group("publisher"),
                url=row.group("url"),
                snapshot_date=row_snapshot.group(1) if row_snapshot else snapshot_date,
                page_count=actual_pages,
                sha256=hashlib.sha256(data).hexdigest(),
                path=candidate,
            )
        )

    parser = ParserIdentity(
        name="opendataloader-pdf",
        version=importlib.metadata.version("opendataloader-pdf"),
    )
    return RunManifest(parser=parser, sources=tuple(sources))
