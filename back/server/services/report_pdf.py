"""증빙 리포트를 PDF 로 굽는다. 내용은 `report.build` 가 만든 것 그대로다.

계약이 `/sessions/{id}/report` 와 `/report.pdf` 를 나란히 두고 **같은 내용**을 요구한다.
그래서 여기서 값을 다시 계산하지 않는다 — `report.build` 의 결과를 받아 그리기만 한다.
두 경로가 다른 수를 말하면 증빙으로서 못 쓴다.

## 왜 이 엔드포인트가 필요한가

상담이 끝나면 서버가 `ended` 메시지에 `report_url` 로 이 경로를 실어 보낸다
(`ws/endpoint.py`). 화면의 "PDF로 저장" 은 그 값이 있으면 새 탭으로 열고, 없을 때만
브라우저 인쇄로 떨어진다. 즉 이 경로가 비어 있으면 **심사위원이 그 버튼을 눌렀을 때
404 가 뜬다.**

## 한글

`HYSMyeongJo-Medium` 은 reportlab 이 들고 있는 Adobe Korean-1 CID 폰트다. 폰트 파일을
레포에 넣지 않아도 되고 이미지도 안 무거워진다. 다만 CID 폰트라 글자 폭을 정확히 재기
어려워, 줄바꿈은 폭이 아니라 **글자 수**로 자른다(`_wrap`).
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

FONT = "HYSMyeongJo-Medium"
MARGIN = 20 * mm
LINE = 5.2 * mm
# 한 줄에 넣을 글자 수. CID 폰트는 폭을 정확히 못 재서 글자 수로 자른다
WIDTH_CHARS = 46

STATE_LABEL = {
    "met": "고지",
    "partial": "부분 고지",
    "unmet": "미고지",
    "waived": "면제",
    "violated": "위반",
    "suspected": "의심",
    "explained": "설명함",
    "confirmed": "이해 확인",
}
AXIS_TITLE = {
    "omission": "필수 고지 (누락 축)",
    "commission": "금지 발언 (위반 축)",
    "comprehension": "고객 이해 (참고)",
}

_registered = False


def _font() -> None:
    """한 프로세스에 한 번만 등록한다. 매번 부르면 요청마다 CMap 을 다시 읽는다."""
    global _registered
    if not _registered:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))
        _registered = True


def _wrap(text: str, width: int = WIDTH_CHARS) -> list[str]:
    text = " ".join(str(text).split())
    return [text[i : i + width] for i in range(0, len(text), width)] or [""]


def _ms(value: Any) -> str:
    try:
        total = int(value) // 1000
    except (TypeError, ValueError):
        return "--:--"
    return f"{total // 60:02d}:{total % 60:02d}"


class _Sheet:
    """줄 단위로 쓰고 자리가 없으면 다음 장으로 넘긴다."""

    def __init__(self, buffer: io.BytesIO) -> None:
        self.c = canvas.Canvas(buffer, pagesize=A4)
        self.c.setTitle("말틈 상담 증빙 리포트")
        self.y = A4[1] - MARGIN

    def line(self, text: str = "", size: float = 9.5, indent: float = 0, gap: float = 0) -> None:
        self.y -= gap
        for part in _wrap(text) if text else [""]:
            if self.y < MARGIN:
                self.c.showPage()
                self.y = A4[1] - MARGIN
            self.c.setFont(FONT, size)
            self.c.drawString(MARGIN + indent, self.y, part)
            self.y -= LINE

    def rule(self) -> None:
        self.y -= 1.5 * mm
        if self.y < MARGIN:
            self.c.showPage()
            self.y = A4[1] - MARGIN
        self.c.line(MARGIN, self.y, A4[0] - MARGIN, self.y)
        self.y -= 3 * mm

    def done(self) -> None:
        self.c.showPage()
        self.c.save()


def render(report: dict[str, Any]) -> bytes:
    """리포트 JSON → PDF 바이트. 값은 만들지 않고 받은 것만 그린다."""
    _font()
    buffer = io.BytesIO()
    sheet = _Sheet(buffer)
    sections = report.get("sections") or {}

    sheet.line("말틈 상담 증빙 리포트", size=15)
    sheet.line(f"세션 {report.get('session_id', '')} · 팩 {report.get('pack_version', '')}", size=9)
    generated = report.get("generated_at")
    sheet.line(f"생성 {generated}", size=9)
    sheet.rule()

    summary = sections.get("summary") or {}
    sheet.line("요약", size=12)
    for label, key in (
        ("필수 항목", "items_total"),
        ("고지", "met"),
        ("부분 고지", "partial"),
        ("미고지", "unmet"),
        ("면제", "waived"),
        ("위반", "violations"),
    ):
        if (value := summary.get(key)) is not None:
            sheet.line(f"{label}: {value}", indent=4 * mm)
    sheet.rule()

    for axis, title in AXIS_TITLE.items():
        rows = sections.get(axis) or []
        if not rows:
            continue
        sheet.line(title, size=12, gap=2 * mm)
        for row in rows:
            state = STATE_LABEL.get(row.get("state"), row.get("state", ""))
            sheet.line(f"[{state}] {row.get('item_code', '')} {row.get('name', '')}", indent=4 * mm)
            # 부분 고지의 값어치는 "무엇이 빠졌나" 에 있다. 그것을 빼면 표가 뜻을 잃는다
            if missing := row.get("missing_elements"):
                sheet.line(f"빠진 요소: {', '.join(missing)}", size=8.5, indent=9 * mm)
            if reason := row.get("waive_reason"):
                sheet.line(f"면제 사유: {reason}", size=8.5, indent=9 * mm)
        sheet.rule()

    # 기획 10.3: 위험 신호는 경보만이 아니라 **확인 기록까지** 남는다
    if risks := sections.get("risk_signals"):
        sheet.line("위험 신호", size=12, gap=2 * mm)
        for risk in risks:
            seen = "확인함" if risk.get("acknowledged") else "미확인"
            sheet.line(
                f"{_ms(risk.get('t_ms'))} [{risk.get('severity', '')}] "
                f"{risk.get('message', '')} — {seen}",
                indent=4 * mm,
            )
        sheet.rule()

    if timeline := sections.get("timeline"):
        sheet.line("타임라인", size=12, gap=2 * mm)
        for row in timeline:
            sheet.line(f"{_ms(row.get('t_ms'))} {row.get('label', '')}", size=8.5, indent=4 * mm)
        sheet.rule()

    # 출처와 면책은 상시 표기 대상이다(계약). 어느 문서 어느 시점 기준인지 남는다
    if sources := report.get("sources"):
        sheet.line("근거 문서", size=12, gap=2 * mm)
        for source in sources:
            if isinstance(source, dict):
                title = source.get("title") or source.get("doc_id", "")
                sheet.line(f"{title} {source.get('published_at', '')}", size=8.5, indent=4 * mm)
            else:
                sheet.line(str(source), size=8.5, indent=4 * mm)
        sheet.rule()

    if disclaimer := report.get("disclaimer"):
        sheet.line(disclaimer, size=8, gap=1 * mm)

    sheet.done()
    return buffer.getvalue()
