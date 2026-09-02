"""규정 원문 → 구조 추출 덤프. **오프라인에서 한 번 돌리고 결과를 커밋한다.**

서버는 추출을 실행하지 않는다. OpenDataLoader 는 JDK 17 이상을 부르는 자바 프로그램인데,
배포 이미지에 JRE 를 넣으면 200MB 가 따라다니고 심사 기간에 자바가 죽으면 검수 화면이
통째로 빈다. 그래서 추출은 여기서 미리 떠서 JSON 으로 커밋하고, 서버는 그 파일을 읽기만
한다(`server/services/extraction.py`).

출력은 **계약(`api.openapi.yaml` 의 `/documents/{doc_id}/extraction`) 모양 그대로**다.
서버가 다시 변환하지 않도록 여기서 계약 모양까지 만들어 둔다 — 변환이 두 곳에 있으면
한쪽만 고쳐진다.

    uv run python scripts/dump_extraction.py            # assets/03_규정문서 전부
    uv run python scripts/dump_extraction.py --doc 05_상품설명서_정기예금
    uv run python scripts/dump_extraction.py --force    # 이미 있어도 다시 뜬다

`rulepack` 을 import 하지 않는다. M3 의 `structure.py` 도 같은 jar 를 부르지만 그쪽 출력은
bbox 를 버려서(청킹 목적) 계약의 `bbox` 를 채울 수 없다. 또 M1 의 운영 스크립트가 M3 의
내부 함수에 묶이면 그쪽 리팩터가 이 스크립트를 깬다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

BACK_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DOCS = BACK_DIR.parent / "assets" / "03_규정문서"
DEFAULT_UPLOADS = BACK_DIR.parent / "uploads" / "documents"
DEFAULT_OUT = BACK_DIR.parent / "assets" / "extraction"

MIN_JDK = 17

# OpenDataLoader 의 노드 종류 → 계약 `blocks[].kind`.
# caption 은 계약 enum 에 없다. 버리지 않고 paragraph 로 둔다 — 표 위의 "☞ 금리 등 …"
# 같은 주석이 캡션으로 잡히는데, 그 문장이 곧 고지 의무의 근거가 되는 자리다.
KIND = {
    "heading": "heading",
    "paragraph": "paragraph",
    "caption": "paragraph",
    "list item": "list_item",
    "table": "table",
    "image": "figure",
}
# 자식만 들고 있는 그릇. 자기 자신은 블록이 아니고 안으로 들어간다
CONTAINERS = ("kids", "list items")


class DumpError(RuntimeError):
    pass


def _java_major(exe: str) -> int | None:
    try:
        proc = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'version "(\d+)(?:\.(\d+))?', proc.stderr + proc.stdout)
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2) or 0)
    return minor if major == 1 else major  # 1.8 → 8


def _java_candidates() -> list[str]:
    out: list[str] = []
    if os.environ.get("JAVA_HOME"):
        home = Path(os.environ["JAVA_HOME"])
        exe = home / "bin" / ("java.exe" if os.name == "nt" else "java")
        if exe.is_file():
            out.append(str(exe))
    roots = [Path("C:/jdk-17")] + sorted((Path.home() / ".jdk").glob("*"), reverse=True)
    for home in roots:
        exe = home / "bin" / ("java.exe" if os.name == "nt" else "java")
        if exe.is_file():
            out.append(str(exe))
    found = shutil.which("java")
    if found:
        out.append(found)
    return out


def _java() -> str:
    """JDK 17 이상의 java 를 찾는다.

    **버전까지 본다.** PATH 에 java 가 있으면 그대로 쓰는 방식은 이 PC 에서 실제로
    깨졌다 — Oracle javapath 가 앞에 있어 Java 8 이 잡히고, jar 는 exit 1 로 죽는데
    메시지가 "OpenDataLoader 실행 실패" 뿐이라 원인이 안 보였다 (2026-09-02).
    """
    seen: list[str] = []
    for cand in _java_candidates():
        version = _java_major(cand)
        if version is None:
            continue
        seen.append(f"{cand} (Java {version})")
        if version >= MIN_JDK:
            return cand
    detail = "  후보: " + " · ".join(seen) if seen else "  java 를 아예 찾지 못했습니다."
    raise DumpError(f"JDK {MIN_JDK} 이상을 찾지 못했습니다. JAVA_HOME 을 설정하세요.\n{detail}")


def _jar() -> Path:
    import opendataloader_pdf

    jar = Path(opendataloader_pdf.__file__).parent / "jar" / "opendataloader-pdf-cli.jar"
    if not jar.is_file():
        raise DumpError(f"jar 이 없습니다: {jar}")
    return jar


def _run(java: str, jar: Path, pdf: Path, out_dir: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            java, "-jar", str(jar), str(pdf),
            "--output-dir", str(out_dir), "--format", "json", "--quiet",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    produced = out_dir / f"{pdf.stem}.json"
    if proc.returncode != 0 or not produced.is_file():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
        joined = "\n  ".join(tail)
        raise DumpError(f"{pdf.name} 추출 실패 (exit {proc.returncode})\n  {joined}")
    return json.loads(produced.read_text(encoding="utf-8"))


def _text(node: Any) -> str:
    """자기 content 가 없으면 자식 텍스트를 잇는다. 표 셀·리스트 항목이 그렇다."""
    if not isinstance(node, dict):
        return ""
    own = node.get("content")
    if isinstance(own, str) and own.strip():
        return own.strip()
    parts = [t for key in CONTAINERS for c in node.get(key, []) if (t := _text(c))]
    return " ".join(parts).strip()


def _table(node: dict[str, Any]) -> dict[str, Any]:
    cells = [
        {"r": int(cell["row number"]), "c": int(cell["column number"]), "text": _text(cell)}
        for row in node.get("rows", [])
        for cell in row.get("cells", [])
    ]
    return {
        "rows": int(node.get("number of rows", 0)),
        "cols": int(node.get("number of columns", 0)),
        "cells": cells,
    }


def _rows_text(table: dict[str, Any]) -> str:
    """표를 읽을 수 있는 한 덩어리로. 행은 줄, 칸은 ` | `.

    L2 임베딩과 근거 스팬이 이 문자열을 본다. 셀을 따로 흘리면 "1년 미만 · 연 2.1%" 처럼
    가로로 이어져야 뜻이 서는 금리표가 낱개 숫자로 흩어진다.
    """
    rows: dict[int, list[tuple[int, str]]] = {}
    for cell in table["cells"]:
        rows.setdefault(cell["r"], []).append((cell["c"], cell["text"]))
    lines = [
        " | ".join(text for _, text in sorted(cells))
        for _, cells in sorted(rows.items())
    ]
    return "\n".join(line for line in lines if line.strip(" |"))


def to_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """계약 `blocks[]` 로 만든다. 순서는 문서 순서 그대로 — 검수 화면이 그 순서로 읽는다."""
    blocks: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return

        kind = KIND.get(str(node.get("type")))
        page = node.get("page number")
        if kind and isinstance(page, int):
            table = _table(node) if kind == "table" else None
            # 표의 글자는 셀 안에 있다. `_text` 는 kids 만 훑어서 표에는 빈 문자열이 온다 —
            # 그대로 두면 표가 통째로 사라진다(실측: 정기예금 설명서의 금리표 5개)
            text = _rows_text(table) if table else _text(node)
            if text or kind == "figure":  # 그림은 텍스트가 없어도 그 자리가 근거다
                # block_id 는 문서 안에서만 유일하면 된다. OpenDataLoader 의 id 는
                # list item 에 없어서(실측) 순번으로 붙인다 — 같은 PDF 면 같은 값이 나온다
                block: dict[str, Any] = {
                    "block_id": f"b{len(blocks) + 1:04d}",
                    "page": page,
                    "kind": kind,
                    "text": text,
                }
                bbox = node.get("bounding box")
                if isinstance(bbox, list) and len(bbox) == 4:
                    # [x1,y1,x2,y2] PDF 포인트, 좌하단 원점. contracts/find_span.py 와 같은
                    # 규약이라 화면이 근거 스팬과 같은 방식으로 덧그린다
                    block["bbox"] = [round(float(v), 1) for v in bbox]
                if table is not None:
                    block["table"] = table
                blocks.append(block)
            if kind == "table":
                return  # 표는 통째로 한 블록. 안의 행·셀을 또 블록으로 만들지 않는다

        for key in CONTAINERS:
            visit(node.get(key, []))

    visit(payload.get("kids", []))
    return blocks


def dump_one(pdf: Path, java: str, jar: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        payload = _run(java, jar, pdf, Path(tmp))
    return {
        "doc_id": pdf.stem,
        "status": "ready",
        "page_count": int(payload.get("number of pages", 0)),
        "blocks": to_blocks(payload),
    }


def _sources(docs: Path, uploads: Path, only: str | None) -> list[Path]:
    found: dict[str, Path] = {}
    for root in (docs, uploads):
        if root.is_dir():
            for pdf in sorted(root.glob("*.pdf")):
                found.setdefault(pdf.stem, pdf)
    if only:
        if only not in found:
            raise DumpError(f"문서를 찾지 못했습니다: {only}\n  있는 것: " + ", ".join(found))
        return [found[only]]
    return list(found.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="규정 원문 구조 추출 덤프 (오프라인)")
    parser.add_argument("--docs-dir", type=Path, default=DEFAULT_DOCS)
    parser.add_argument("--uploads-dir", type=Path, default=DEFAULT_UPLOADS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--doc", help="doc_id 하나만")
    parser.add_argument("--force", action="store_true", help="이미 있어도 다시 뜬다")
    args = parser.parse_args(argv)

    try:
        pdfs = _sources(args.docs_dir, args.uploads_dir, args.doc)
        if not pdfs:
            raise DumpError(f"PDF 가 없습니다: {args.docs_dir}")
        java, jar = _java(), _jar()
    except DumpError as e:
        print(f"[실패] {e}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    made = skipped = failed = 0
    for pdf in pdfs:
        target = args.out / f"{pdf.stem}.json"
        if target.exists() and not args.force:
            print(f"[건너뜀] {pdf.stem} — 이미 있음 (--force 로 다시)")
            skipped += 1
            continue
        try:
            result = dump_one(pdf, java, jar)
        except DumpError as e:
            print(f"[실패] {e}", file=sys.stderr)
            failed += 1
            continue
        target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", "utf-8")
        print(f"[완료] {pdf.stem} — {result['page_count']}쪽 {len(result['blocks'])}블록")
        made += 1

    print(f"\n뜬 것 {made} · 건너뜀 {skipped} · 실패 {failed} → {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
