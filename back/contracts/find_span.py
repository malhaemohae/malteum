#!/usr/bin/env python3
"""인용 문자열의 페이지·문자 좌표를 찾는다.

기능 ⑭(근거 원문 점프)와 P4(근거 스팬 없는 항목은 항목이 아니다)가 실제로
성립하는지를 이 한 함수가 결정한다. 규정 팩 발행 파이프라인이 항목마다 이걸 부른다.

  - 원문에 실재하지 않는 인용은 좌표를 못 만든다  → 항목 폐기 (P4 의 기계적 관문)
  - 실재하면 bbox 를 만든다                        → 화면이 그 사각형을 덧그린다 (⑭)

OpenDataLoader 의 bbox 는 요소 단위(문단 전체)라 문장 하이라이트가 안 된다.
그래서 문자 단위 좌표는 pypdfium2 로 따로 뜬다. 두 도구의 역할 분담이 이것이다.

사용
    python tools/find_span.py 03_규정문서/05_상품설명서_정기예금.pdf "1개월 미만: 연 0.10%"
    python tools/find_span.py <pdf> <span> --json
"""

from __future__ import annotations

import argparse
import json
import sys

import pypdfium2 as pdfium

sys.stdout.reconfigure(encoding="utf-8")


def find_span(pdf_path: str, span: str, page_hint: int | None = None) -> dict | None:
    """span 을 담은 첫 페이지의 문자 좌표 합집합을 돌려준다.

    반환 bbox 는 [x1, y1, x2, y2] PDF 포인트. 좌하단 원점이며 y 가 위로 자란다.
    화면에서 CSS 로 덧그릴 때는 y 를 뒤집어야 한다 (page_height - y2).
    """
    doc = pdfium.PdfDocument(pdf_path)
    pages = [page_hint - 1] if page_hint else range(len(doc))

    for i in pages:
        page = doc[i]
        tp = page.get_textpage()
        searcher = tp.search(span, match_case=True, match_whole_word=False)
        found = searcher.get_next()
        if found is None:
            # PDF 는 줄바꿈을 문자로 넣는다. 한 줄에 담기지 않는 인용은 여기서 실패한다.
            # 팩 발행 시에는 한 줄 단위로 인용을 자르는 것이 규칙이다.
            continue

        char_index, char_count = found
        boxes = [tp.get_charbox(char_index + n, loose=False) for n in range(char_count)]
        boxes = [b for b in boxes if b and (b[2] - b[0]) > 0]
        if not boxes:
            continue

        x1 = min(b[0] for b in boxes)
        y1 = min(b[1] for b in boxes)
        x2 = max(b[2] for b in boxes)
        y2 = max(b[3] for b in boxes)

        return {
            "page": i + 1,
            "span": span,
            "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            "page_size": [round(page.get_width(), 1), round(page.get_height(), 1)],
            "char_index": char_index,
            "char_count": char_count,
        }
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("span")
    ap.add_argument("--page", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    hit = find_span(a.pdf, a.span, a.page)
    if hit is None:
        print(f"없음: {a.span!r}")
        return 1
    if a.json:
        print(json.dumps(hit, ensure_ascii=False))
    else:
        print(f"p{hit['page']}  bbox={hit['bbox']}  page={hit['page_size']}  chars={hit['char_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
