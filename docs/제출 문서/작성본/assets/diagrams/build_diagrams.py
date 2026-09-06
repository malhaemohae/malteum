"""Five submission diagrams in the diagram-design default skin.

Default tokens only (style-guide.md of cathrynlavery/diagram-design): paper #f5f5f5,
ink #2d3142, muted #4f5d75, soft #7a8399, accent #eb6c36, link #2e5aa8. Geist /
Geist Mono / Instrument Serif from Google Fonts; Hangul falls back to the system
sans. Every coordinate is a multiple of 4, connectors are orthogonal with r=8
elbows, arrow labels sit on an opaque mask with a 6-10px gap, legend is a bottom strip.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAPER, INK, MUTED, SOFT, ACCENT, LINK = "#f5f5f5", "#2d3142", "#4f5d75", "#7a8399", "#eb6c36", "#2e5aa8"
SANS = "'Geist', 'Malgun Gothic', system-ui, sans-serif"
MONO = "'Geist Mono', 'Malgun Gothic', ui-monospace, monospace"
SERIF = "'Instrument Serif', 'Malgun Gothic', serif"

KIND = {  # fill, stroke, tag stroke, tag text
    "focal": ("rgba(235,108,54,0.08)", ACCENT, "rgba(235,108,54,0.50)", ACCENT),
    "step": ("#ffffff", INK, "rgba(45,49,66,0.40)", INK),
    "store": ("rgba(45,49,66,0.05)", MUTED, "rgba(79,93,117,0.50)", MUTED),
    "external": ("rgba(45,49,66,0.03)", "rgba(45,49,66,0.30)", "rgba(45,49,66,0.22)", SOFT),
    "input": ("rgba(79,93,117,0.10)", SOFT, "rgba(122,131,153,0.40)", SOFT),
    "optional": ("rgba(45,49,66,0.02)", "rgba(45,49,66,0.20)", "rgba(45,49,66,0.20)", SOFT),
}


def r4(value: float) -> int:
    return int(round(value / 4.0)) * 4


def text_width(text: str, size: float) -> int:
    width = 0.0
    for ch in text:
        width += size * (1.0 if ord(ch) > 0x2E7F else 0.62)
    return r4(width + 8)


class Svg:
    def __init__(self, slug: str, title: str, desc: str, width: int, height: int) -> None:
        self.slug, self.title, self.desc, self.w, self.h = slug, title, desc, width, height
        self.zones: list[str] = []
        self.arrows: list[str] = []
        self.labels: list[str] = []
        self.nodes: list[str] = []
        self.notes: list[str] = []
        self.legend_items: list[tuple[str, str]] = []
        self.dy = 0  # content shift; the legend stays anchored to the bottom

    # --- zones ------------------------------------------------------------------
    def zone(self, x: int, y: int, w: int, h: int, label: str) -> None:
        lw = text_width(label, 7)
        self.zones.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="rgba(45,49,66,0.02)" stroke="rgba(45,49,66,0.10)" stroke-width="0.8"/>'
            f'<rect x="{x + 12}" y="{y + 4}" width="{lw}" height="12" rx="2" fill="{PAPER}"/>'
            f'<text x="{x + 12 + lw // 2}" y="{y + 13}" fill="rgba(45,49,66,0.45)" font-size="7" font-family="{MONO}" text-anchor="middle" letter-spacing="0.14em">{label}</text>'
        )

    # --- connectors -------------------------------------------------------------
    def arrow(self, d: str, kind: str = "default", dashed: bool = False) -> None:
        stroke = {"default": MUTED, "accent": ACCENT, "link": LINK}[kind]
        marker = {"default": "arrow", "accent": "arrow-accent", "link": "arrow-link"}[kind]
        width = 1.4 if kind == "accent" else (1 if dashed else 1.2)
        dash = ' stroke-dasharray="4,3"' if dashed else ""
        self.arrows.append(f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{width}"{dash} marker-end="url(#{marker})"/>')

    def line(self, x1: int, y1: int, x2: int, y2: int, kind: str = "default", dashed: bool = False) -> None:
        self.arrow(f"M {x1},{y1} L {x2},{y2}", kind, dashed)

    def label(self, cx: int, y_top: int, text: str, color: str = MUTED) -> None:
        """Arrow label on an opaque mask. y_top is the mask's top edge (12px tall)."""
        w = text_width(text, 8)
        self.labels.append(
            f'<rect x="{cx - w // 2}" y="{y_top}" width="{w}" height="12" rx="2" fill="{PAPER}"/>'
            f'<text x="{cx}" y="{y_top + 9}" fill="{color}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">{text}</text>'
        )

    # --- nodes ------------------------------------------------------------------
    def node(self, x: int, y: int, w: int, h: int, name: str, sub: str, kind: str, tag: str, shape: str = "box") -> None:
        fill, stroke, tag_stroke, tag_text = KIND[kind]
        dash = ' stroke-dasharray="4,3"' if kind == "optional" else ""
        rx = 28 if shape == "oval" else 6
        cx, cy = x + w // 2, y + h // 2
        parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{PAPER}"/>',
                 f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1"{dash}/>']
        if tag and shape == "box":
            raw = sum(7 * (1.0 if ord(ch) > 0x2E7F else 0.62) for ch in tag) + 7 * 0.08 * len(tag)
            tw = r4(raw + 10)
            parts.append(f'<rect x="{x + 8}" y="{y + 6}" width="{tw}" height="12" rx="2" fill="transparent" stroke="{tag_stroke}" stroke-width="0.8"/>'
                         f'<text x="{x + 8 + tw // 2}" y="{y + 15}" fill="{tag_text}" font-size="7" font-family="{MONO}" text-anchor="middle" letter-spacing="0.08em">{tag}</text>')
        for label, size in ((name, 12), (sub, 9)):
            if label and text_width(label, size) > w:
                raise ValueError(f"{label!r} 이 {w}px 노드를 넘칩니다 ({text_width(label, size)}px)")
        name_y = cy + (2 if not sub else -2) + (4 if tag and shape == "box" else 0)
        parts.append(f'<text x="{cx}" y="{name_y}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{name}</text>')
        if sub:
            parts.append(f'<text x="{cx}" y="{name_y + 16}" fill="{MUTED}" font-size="9" font-family="{MONO}" text-anchor="middle">{sub}</text>')
        self.nodes.append("".join(parts))

    def diamond(self, cx: int, cy: int, hw: int, hh: int, name: str, sub: str = "") -> None:
        pts = f"{cx},{cy - hh} {cx + hw},{cy} {cx},{cy + hh} {cx - hw},{cy}"
        self.nodes.append(
            f'<polygon points="{pts}" fill="{PAPER}"/><polygon points="{pts}" fill="#ffffff" stroke="{INK}" stroke-width="1" stroke-linejoin="round"/>'
            f'<text x="{cx}" y="{cy + (2 if not sub else -2)}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{name}</text>'
            + (f'<text x="{cx}" y="{cy + 14}" fill="{MUTED}" font-size="9" font-family="{MONO}" text-anchor="middle">{sub}</text>' if sub else "")
        )

    def dot(self, cx: int, cy: int) -> None:
        self.nodes.append(f'<circle cx="{cx}" cy="{cy}" r="4" fill="{INK}"/>')

    def aside(self, x: int, y: int, text: str, anchor: str = "start") -> None:
        self.notes.append(f'<text x="{x}" y="{y}" fill="{MUTED}" font-size="12" font-style="italic" font-family="{SERIF}" text-anchor="{anchor}">{text}</text>')

    # --- legend -----------------------------------------------------------------
    def legend(self, items: list[tuple[str, str]]) -> None:
        self.legend_items = items

    def hlabel(self, cx: int, line_y: int, text: str, color: str = MUTED, above: bool = True) -> None:
        """가로 연결선 라벨. 마스크와 선 사이에 8px 를 둔다."""
        self.label(cx, line_y - 20 if above else line_y + 8, text, color)

    def vlabel(self, line_x: int, y_top: int, text: str, color: str = MUTED, side: int = 1) -> None:
        """세로 연결선 라벨. 선 옆으로 8px 떨어뜨린다."""
        w = text_width(text, 8)
        self.label(line_x + side * (8 + w // 2), y_top, text, color)

    def legend_rows(self) -> int:
        x, rows = 40, 1
        for kind, text in self.legend_items:
            item = (20 if kind in KIND else 36) + text_width(text, 8.5) + 20
            if x > 40 and x + item > self.w - 40:
                rows += 1
                x = 40
            x += item
        return rows

    def render_legend(self, y: int) -> str:
        out = [f'<line x1="40" y1="{y}" x2="{self.w - 40}" y2="{y}" stroke="rgba(45,49,66,0.10)" stroke-width="0.8"/>',
               f'<text x="40" y="{y + 16}" fill="{MUTED}" font-size="8" font-family="{MONO}" letter-spacing="0.18em">범례</text>']
        x, row = 40, 0
        for kind, text in self.legend_items:
            item = (20 if kind in KIND else 36) + text_width(text, 8.5) + 20
            if x > 40 and x + item > self.w - 40:
                row += 1
                x = 40
            sy = y + 32 + row * 22
            if kind in KIND:
                fill, stroke, _, _ = KIND[kind]
                dash = ' stroke-dasharray="3,2"' if kind == "optional" else ""
                out.append(f'<rect x="{x}" y="{sy}" width="14" height="10" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1"{dash}/>')
                tx = x + 20
            else:
                stroke = {"default": MUTED, "accent": ACCENT, "link": LINK, "dashed": MUTED}[kind]
                dash = ' stroke-dasharray="4,3"' if kind == "dashed" else ""
                marker = {"default": "arrow", "dashed": "arrow", "accent": "arrow-accent", "link": "arrow-link"}[kind]
                out.append(f'<line x1="{x}" y1="{sy + 5}" x2="{x + 28}" y2="{sy + 5}" stroke="{stroke}" stroke-width="1.2"{dash} marker-end="url(#{marker})"/>')
                tx = x + 36
            out.append(f'<text x="{tx}" y="{sy + 8}" fill="{MUTED}" font-size="8.5" font-family="{SANS}">{text}</text>')
            x = tx + text_width(text, 8.5) + 20
        return "".join(out)

    # --- output -----------------------------------------------------------------
    def svg(self) -> str:
        legend_y = self.h - (48 + 24 * self.legend_rows())
        return (
            f'<svg viewBox="0 0 {self.w} {self.h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{self.slug}-title {self.slug}-desc">'
            f'<title id="{self.slug}-title">{self.title}</title><desc id="{self.slug}-desc">{self.desc}</desc>'
            '<defs>'
            f'<marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{MUTED}"/></marker>'
            f'<marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{ACCENT}"/></marker>'
            f'<marker id="arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{LINK}"/></marker>'
            '</defs>'
            f'<rect width="100%" height="100%" fill="{PAPER}"/>'
            + f'<g transform="translate(0,{self.dy})">' + "".join(self.zones) + "".join(self.arrows) + "".join(self.labels) + "".join(self.nodes) + "".join(self.notes) + "</g>"
            + self.render_legend(legend_y)
            + "</svg>"
        )

    def html(self, eyebrow: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{self.title}</title>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{ --color-paper: {PAPER}; --color-ink: {INK}; --color-muted: {MUTED}; --color-accent: {ACCENT};
      --font-sans: {SANS}; --font-serif: {SERIF}; --font-mono: {MONO}; }}
    body {{ font-family: var(--font-sans); background: var(--color-paper); color: var(--color-ink); min-height: 100vh;
      display: flex; align-items: center; justify-content: center; padding: 3rem 2rem; }}
    .frame {{ max-width: 1200px; width: 100%; }}
    .eyebrow {{ font-family: var(--font-mono); font-size: 0.66rem; font-weight: 500; letter-spacing: 0.18em; text-transform: uppercase; color: var(--color-muted); margin-bottom: 0.5rem; }}
    h1 {{ font-family: var(--font-serif); font-size: clamp(1.5rem, 2.4vw + 0.75rem, 2rem); font-weight: 400; letter-spacing: -0.02em; line-height: 1.15; color: var(--color-ink); margin-bottom: 1.5rem; }}
    svg {{ width: 100%; max-width: 760px; margin: 0 auto; display: block; }}
  </style>
</head>
<body>
  <div class="frame">
    <p class="eyebrow">{eyebrow}</p>
    <h1>{self.title}</h1>
    {self.svg()}
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------------
def d01_system() -> Svg:
    s = Svg("01-system", "말틈 전체 구성",
            "상담원 브라우저가 서버의 화면·게이트웨이·내장 엔진·저장소와 연결되고, 음성 인식과 언어 모델은 설정에 따라 외부 추론으로 붙는 구성", 720, 720)
    # 열 48/276/504 (너비 168), 행 72/200/328/456 (높이 64)
    s.zone(32, 176, 428, 376, "서버 · 한 배포 단위")
    s.zone(488, 304, 200, 248, "외부 추론 · 설정 의존")
    s.line(360, 136, 360, 200, "link"); s.vlabel(360, 152, "HTTPS", LINK)
    s.line(360, 264, 360, 328); s.vlabel(360, 282, "실시간·조회")
    s.line(276, 344, 220, 344); s.hlabel(248, 344, "기록 추가")
    s.line(216, 372, 272, 372, dashed=True); s.hlabel(248, 372, "복원", above=False)
    s.line(360, 392, 360, 456); s.vlabel(360, 410, "판정")
    s.line(216, 488, 272, 488); s.hlabel(244, 488, "불러오기")
    s.line(444, 344, 500, 344); s.hlabel(472, 344, "음성")
    s.line(504, 372, 448, 372, dashed=True); s.hlabel(476, 372, "문장·화자", above=False)
    s.line(444, 488, 500, 488); s.hlabel(472, 488, "재판정")
    s.node(276, 72, 168, 64, "상담원 브라우저", "음성 · 질문 · 조치", "input", "USER")
    s.node(276, 200, 168, 64, "프론트엔드", "상담 화면 · 근거 뷰어", "step", "WEB")
    s.node(48, 328, 168, 64, "상담 기록", "덧붙이기 전용", "store", "DB")
    s.node(276, 328, 168, 64, "게이트웨이", "WebSocket + REST", "focal", "API")
    s.node(504, 328, 168, 64, "음성 인식·화자 분리", "발화 · 화자 구간", "external", "STT")
    s.node(48, 456, 168, 64, "승인된 규정팩", "버전 고정 파일", "store", "PACK")
    s.node(276, 456, 168, 64, "내장 엔진", "규칙 · 검색 · 재판정", "step", "ENGINE")
    s.node(504, 456, 168, 64, "언어 모델", "재판정 · 역할 추정", "external", "LLM")
    s.legend([("focal", "게이트웨이"), ("step", "서버 구성요소"), ("store", "저장소"), ("external", "외부 추론"),
              ("link", "브라우저 접속"), ("default", "주요 흐름"), ("dashed", "반환 · 복구")])
    return s


def d02_engine() -> Svg:
    s = Svg("02-engine", "엔진 판정 흐름 · 빠른 판정과 늦게 오는 재판정",
            "받아쓴 문장이 다듬기, 규칙 판정, 검색을 거쳐 즉시 화면에 반영되고, 필요할 때만 언어 모델 재판정이 뒤따라 앞선 판단을 대체하는 흐름", 720, 720)
    # 왼쪽 48 · 오른쪽 480 (너비 192), 행 40/136/232/328/520 (높이 56)
    s.line(144, 96, 144, 136); s.vlabel(144, 102, "치환")
    s.line(144, 192, 144, 232); s.vlabel(144, 198, "규칙")
    s.line(144, 288, 144, 328); s.vlabel(144, 294, "검색")
    s.line(240, 260, 476, 260, "accent"); s.hlabel(358, 260, "즉시 반영", ACCENT)
    s.line(144, 384, 144, 416); s.vlabel(144, 390, "미해결")
    s.line(144, 484, 144, 520); s.vlabel(144, 494, "예")
    s.arrow("M 240,452 H 400 Q 408,452 408,444 V 288 Q 408,280 416,280 H 476")
    s.vlabel(408, 356, "아니요 · 유지")
    s.line(240, 548, 476, 548); s.hlabel(358, 548, "제약 통과")
    s.line(576, 520, 576, 292, dashed=True); s.vlabel(576, 396, "판단 갱신")
    s.node(48, 40, 192, 56, "확정 발화", "화자 · 신뢰도 · 시각", "input", "", shape="oval")
    s.node(48, 136, 192, 56, "0단계: 다듬기", "규정팩 용어로 맞춤", "step", "")
    s.node(48, 232, 192, 56, "1단계: 규칙", "요건 · 표현 · 수치", "step", "")
    s.node(480, 232, 192, 56, "화면 반영", "판정 · 경보 · 안내 카드", "step", "OUT")
    s.node(48, 328, 192, 56, "2단계: 검색", "자모 트라이그램 · 임베딩", "step", "")
    s.diamond(144, 452, 96, 32, "재판정 필요?", "부분 충족 · 의심")
    s.node(48, 520, 192, 56, "3단계: 재판정", "LLM · 허용 후보만 · 시간 예산", "focal", "")
    s.node(480, 520, 192, 56, "결과 기록·연결", "앞선 판단을 대체", "store", "LOG")
    s.legend([("focal", "LLM 판정"), ("step", "규칙·검색 단계"), ("store", "기록"),
              ("accent", "즉시 반영 경로"), ("default", "흐름"), ("dashed", "뒤늦게 도착하는 갱신")])
    return s


def d03_correction() -> Svg:
    s = Svg("03-correction", "받아쓴 문장 교정 · 원문을 보존하는 제한적 보완",
            "받아쓴 문장이 규정팩 용어로 보완되고, 재판정 경로에서만 선택적으로 언어 모델이 허용 후보 안에서 용어 조합을 고르며, 검사에 실패하면 원래 해석으로 진행하는 흐름", 720, 720)
    # 왼쪽 88 · 오른쪽 480 (너비 192), 행 40/136/232/424/520 (높이 56)
    s.line(280, 68, 476, 68, dashed=True); s.hlabel(378, 68, "원문 보존")
    s.line(184, 96, 184, 136); s.vlabel(184, 102, "다듬기")
    s.line(184, 192, 184, 232); s.vlabel(184, 198, "용어 짝")
    s.line(184, 288, 184, 320); s.vlabel(184, 294, "모호 후보")
    s.arrow("M 280,356 H 400 Q 408,356 408,348 V 252 Q 408,244 416,244 H 476")
    s.vlabel(408, 296, "현재 해석 유지", side=-1)
    s.line(184, 388, 184, 424); s.vlabel(184, 398, "예")
    s.line(184, 480, 184, 520); s.vlabel(184, 486, "조합 선택")
    s.arrow("M 280,540 H 432 Q 440,540 440,532 V 270 Q 440,262 448,262 H 476")
    s.vlabel(440, 400, "허용 조합만", side=-1)
    s.arrow("M 280,564 H 448 Q 456,564 456,556 V 288 Q 456,280 464,280 H 476", dashed=True)
    s.vlabel(456, 452, "범위 밖 · 실패")
    s.node(88, 40, 192, 56, "확정 은행원 발화", "받아쓴 그대로", "input", "", shape="oval")
    s.node(480, 40, 192, 56, "확정 발화 기록", "원문 · 수치 그대로", "store", "DB")
    s.node(88, 136, 192, 56, "규칙 보완", "규정팩 용어 · 띄어쓰기", "step", "RULE")
    s.node(88, 232, 192, 56, "후보 선별", "모호한 낱말 · 용어 짝", "step", "SCOPE")
    s.node(480, 232, 192, 56, "재판정 입력", "판정에 쓸 해석", "step", "JUDGE")
    s.diamond(184, 356, 96, 32, "보조 교정 사용?", "선택 연결점")
    s.node(88, 424, 192, 56, "교정 에이전트", "LLM · 허용 후보 조합 선택", "focal", "LLM")
    s.node(88, 520, 192, 56, "조합 재검사", "허용 후보인지 · 짝이 맞는지", "step", "CHECK")
    s.legend([("focal", "LLM (선택)"), ("step", "규칙·검사 단계"), ("store", "저장"),
              ("default", "흐름"), ("dashed", "보존 · 우회")])
    return s


def d04_rulepack() -> Svg:
    s = Svg("04-rulepack", "규정팩 구축 · 원문에서 승인된 기준까지",
            "공개 규정 문서가 구조 추출, 후보 생성, 근거 대조, 사람 검수를 거쳐 버전이 고정된 규정팩으로 발행되고, 상담 중에는 그 규정팩을 읽기만 하는 흐름", 720, 720)
    # 열 56/280/504 (너비 160), 행 76/196/308/456
    s.zone(40, 44, 644, 348, "상담 전 · 규정 분석과 사람 검수")
    s.zone(40, 424, 644, 160, "상담 중 · 읽기 전용")
    s.line(216, 108, 276, 108); s.hlabel(246, 108, "PDF")
    s.line(440, 108, 500, 108); s.hlabel(470, 108, "구조화")
    s.arrow("M 584,140 V 164 Q 584,172 576,172 H 144 Q 136,172 136,180 V 192")
    s.hlabel(360, 172, "후보")
    s.line(216, 228, 276, 228, "accent"); s.hlabel(246, 228, "검수 요청", ACCENT)
    s.line(136, 260, 136, 304, dashed=True); s.vlabel(136, 272, "근거 없음")
    s.arrow("M 440,228 H 576 Q 584,228 584,236 V 448")
    s.vlabel(584, 336, "발행")
    s.line(504, 488, 444, 488); s.hlabel(474, 488, "불러오기")
    s.line(280, 488, 220, 488); s.hlabel(250, 488, "조회")
    s.node(56, 76, 160, 64, "원천 문서", "법령 · 약관 · 상품설명서", "input", "SRC")
    s.node(280, 76, 160, 64, "구조 추출", "표 · 제목 계층 복원", "step", "PARSE")
    s.node(504, 76, 160, 64, "후보 생성", "언어 모델 추출", "step", "DRAFT")
    s.node(56, 196, 160, 64, "근거 대조", "구절 · 페이지 · 좌표", "focal", "CHECK")
    s.node(280, 196, 160, 64, "사람 검수·승인", "검토 대기열 · 승인 서명", "step", "REVIEW")
    s.node(56, 308, 160, 48, "자동 폐기", "근거 없는 항목", "optional", "")
    s.node(504, 456, 160, 64, "발행된 규정팩", "버전 고정 · 불변", "store", "PACK")
    s.node(280, 456, 160, 64, "저장·색인", "빠르게 찾도록 정리", "store", "DB")
    s.node(56, 456, 160, 64, "상담 진행", "그 상담의 판단 기준", "step", "RUN")
    s.legend([("focal", "근거 검증"), ("step", "처리 단계"), ("store", "산출물 · 저장"),
              ("optional", "자동 폐기"), ("accent", "검수 대기"), ("default", "흐름")])
    return s


def d05_userflow() -> Svg:
    s = Svg("05-userflow", "상담원의 사용 흐름 · 접속에서 종료 기록까지",
            "상담원이 접속해 규정 기준을 확인하고 상담을 진행하는 동안 안내·경보를 근거 원문으로 확인해 설명을 보완하며, 종료 후 리포트를 남기는 흐름", 720, 720)
    # 왼쪽 64 · 오른쪽 448 (너비 208), 행 64/176/288/400/512 (높이 64)
    s.line(168, 128, 168, 176); s.vlabel(168, 142, "시작")
    s.line(168, 240, 168, 288); s.vlabel(168, 254, "기준 확인")
    s.line(272, 320, 444, 320, "accent"); s.hlabel(358, 320, "경보 발생", ACCENT)
    s.line(552, 352, 552, 400); s.vlabel(552, 366, "근거 보기")
    s.line(552, 464, 552, 512); s.vlabel(552, 478, "보완 설명")
    s.arrow("M 448,544 H 360 Q 352,544 352,536 V 344 Q 352,336 344,336 H 276", dashed=True)
    s.vlabel(352, 428, "상담 계속")
    s.line(168, 352, 168, 400); s.vlabel(168, 366, "종료")
    s.line(168, 464, 168, 512); s.vlabel(168, 478, "기록")
    s.node(64, 64, 208, 64, "접속", "설치 없이 브라우저로", "input", "", shape="oval")
    s.node(64, 176, 208, 64, "상담 준비", "규정팩 · 필수 안내 · 서류", "step", "01")
    s.node(64, 288, 208, 64, "상담 진행", "녹음 또는 텍스트 · 실시간 전사", "focal", "02")
    s.node(448, 288, 208, 64, "안내·경보 확인", "미고지 · 수치 · 금지 표현", "step", "A")
    s.node(64, 400, 208, 64, "상담 종료", "종료 버튼 한 번", "step", "03")
    s.node(448, 400, 208, 64, "근거 원문", "형광펜 · 주변 문맥 · 페이지", "step", "B")
    s.node(64, 512, 208, 64, "종료 리포트", "항목별 기록 · PDF 저장", "step", "04")
    s.node(448, 512, 208, 64, "설명 보완·조치 기록", "고지 기록 · 제외 · 확인", "step", "C")
    s.legend([("focal", "상담 화면"), ("step", "화면 · 행동"), ("input", "진입"),
              ("accent", "확인 필요"), ("default", "흐름"), ("dashed", "반복 (상담 중 여러 번)")])
    return s


DIAGRAMS = [d01_system, d02_engine, d03_correction, d04_rulepack, d05_userflow]
EYEBROWS = {"01-system": "Architecture · Diagram Design", "02-engine": "Flowchart · Diagram Design", "03-correction": "Flowchart · Diagram Design", "04-rulepack": "Process · Diagram Design", "05-userflow": "Flowchart · Diagram Design"}


def check(svg: str, slug: str) -> list[str]:
    problems = []
    for m in re.finditer(r'(?:x|y|x1|y1|x2|y2|cx|cy|width|height)="(-?\d+(?:\.\d+)?)"', svg):
        value = float(m.group(1))
        if value.is_integer() and int(value) % 4 and int(value) not in (14, 10, 12, 28, 7, 9):
            problems.append(f"{slug}: off-grid {m.group(0)}")
    return problems


def main() -> None:
    manifest = []
    problems: list[str] = []
    for build in DIAGRAMS:
        s = build()
        (HERE / f"{s.slug}.html").write_text(s.html(EYEBROWS[s.slug]), encoding="utf-8")
        (HERE / f"{s.slug}.svg").write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + s.svg() + "\n", encoding="utf-8")
        manifest.append({"slug": s.slug, "title": s.title, "size": [s.w, s.h]})
        problems += check(s.svg(), s.slug)
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    for p in problems:
        print("WARN", p)


if __name__ == "__main__":
    main()
