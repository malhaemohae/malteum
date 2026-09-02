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
    r"(?P<pages>\d+)p\s*/",
    re.MULTILINE,
)


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
    if len(rows) != 7:
        raise ManifestError(f"MANIFEST PDF 행은 7개여야 함: {len(rows)}개")

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

        try:
            actual_pages = len(pdfium.PdfDocument(candidate))
        except Exception as exc:
            raise ManifestError(f"PDF 열기 실패: {filename}: {exc}") from exc
        declared_pages = int(row.group("pages"))
        if actual_pages != declared_pages:
            raise ManifestError(
                f"page_count 불일치: {filename}: MANIFEST={declared_pages}, PDF={actual_pages}"
            )

        sources.append(
            SourceRecord(
                doc_id=doc_id,
                title=row.group("title"),
                publisher=row.group("publisher"),
                url=row.group("url"),
                snapshot_date=snapshot_date,
                page_count=actual_pages,
                sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                path=candidate,
            )
        )

    parser = ParserIdentity(
        name="opendataloader-pdf",
        version=importlib.metadata.version("opendataloader-pdf"),
    )
    return RunManifest(parser=parser, sources=tuple(sources))
