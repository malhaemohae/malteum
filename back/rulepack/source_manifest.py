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


_PUBLISHERS = {
    "01_금융소비자보호법": "법제처",
    "02_설명의무_이행_가이드라인": "금융위원회·금융감독원",
    "03_예금거래기본약관": "한국씨티은행",
    "04_은행여신거래기본약관_가계용": "우리은행",
    "05_상품설명서_정기예금": "신한은행",
    "06_상품설명서_가계대출": "하나은행",
    "07_제2차_금융분야_보이스피싱_대책": "금융위원회",
}

_SNAPSHOT_RE = re.compile(r"수집 확인\s+(\d{4}-\d{2}-\d{2})")
# 제목 링크 앞의 칸은 1개(분류)였다가 발행 기관 열이 추가되어 2개가 됨 (2026-08-27).
# 위치가 아니라 "링크가 나오는 칸"을 찾도록 1~2칸을 허용한다.
_ROW_RE = re.compile(
    r"^\|\s*`(?P<filename>[^`]+\.pdf)`\s*\|(?:[^|]*\|){1,2}\s*"
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
                publisher=_PUBLISHERS[doc_id],
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
