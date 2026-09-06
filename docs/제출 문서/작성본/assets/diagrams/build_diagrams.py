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
            tw = text_width(tag, 7) - 4
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

    def render_legend(self, y: int) -> str:
        out = [f'<line x1="40" y1="{y}" x2="{self.w - 40}" y2="{y}" stroke="rgba(45,49,66,0.10)" stroke-width="0.8"/>',
               f'<text x="40" y="{y + 16}" fill="{MUTED}" font-size="8" font-family="{MONO}" letter-spacing="0.18em">범례</text>']
        x = 40
        for kind, text in self.legend_items:
            sy = y + 32
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
        legend_y = self.h - 72
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
    svg {{ width: 100%; min-width: 900px; display: block; }}
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
    s = Svg("01-system", "말틈 전체 구성", "상담원 브라우저가 서버의 화면·게이트웨이·내장 엔진·저장소와 연결되고, 음성 인식과 언어 모델은 설정에 따라 외부 추론으로 붙는 구성", 1000, 448)
    s.dy = -96
    s.zone(196, 196, 600, 244, "서버 · 한 배포 단위")
    s.zone(800, 136, 176, 272, "외부 추론 · 설정 의존")
    # arrows first
    s.line(168, 264, 216, 264, "link"); s.label(192, 244, "HTTPS", LINK)
    s.line(344, 264, 400, 264); s.label(372, 244, "실시간·조회")
    s.line(480, 296, 480, 344); s.label(512, 312, "판정")
    s.line(560, 248, 616, 248); s.label(588, 228, "기록 추가")
    s.line(616, 280, 560, 280, dashed=True); s.label(588, 288, "복원")
    s.line(344, 376, 400, 376); s.label(372, 356, "불러오기")
    s.arrow("M 480,232 V 184 Q 480,176 488,176 H 816"); s.label(700, 156, "음성")
    s.arrow("M 816,208 H 528 Q 520,208 520,216 V 232", dashed=True); s.label(700, 216, "문장 · 화자")
    s.arrow("M 560,376 H 788 Q 796,376 796,368 V 360 Q 796,352 804,352 H 816"); s.label(688, 356, "재판정 · 안내")
    # nodes
    s.node(40, 232, 128, 64, "상담원 브라우저", "음성 · 질문 · 조치", "input", "USER")
    s.node(216, 232, 128, 64, "프론트엔드", "상담 화면 · 근거 뷰어", "step", "WEB")
    s.node(400, 232, 160, 64, "게이트웨이", "WebSocket + REST", "focal", "API")
    s.node(400, 344, 160, 64, "내장 엔진", "규칙 · 검색 · 재판정", "step", "ENGINE")
    s.node(616, 232, 144, 64, "상담 기록", "덧붙이기 전용", "store", "DB")
    s.node(216, 344, 128, 64, "승인된 규정 팩", "버전 고정 파일", "store", "PACK")
    s.node(816, 160, 144, 64, "음성 인식·화자 분리", "발화 · 화자 구간", "external", "STT")
    s.node(816, 320, 144, 64, "언어 모델", "재판정 · 역할 추정", "external", "LLM")
    s.legend([("focal", "게이트웨이"), ("step", "서버 구성요소"), ("store", "저장소"), ("external", "외부 추론"), ("link", "브라우저 접속"), ("default", "주요 흐름"), ("dashed", "반환 · 복구")])
    return s


def d02_engine() -> Svg:
    s = Svg("02-engine", "엔진 판정 흐름 · 빠른 판정과 늦게 오는 재판정", "받아쓴 문장이 다듬기, 규칙 판정, 검색을 거쳐 즉시 화면에 반영되고, 필요할 때만 언어 모델 재판정이 뒤따라 앞선 판단을 대체하는 흐름", 1000, 424)
    s.dy = -152
    # row 1 arrows
    s.line(168, 228, 216, 228); s.label(192, 208, "치환")
    s.line(336, 228, 384, 228); s.label(360, 208, "규칙")
    s.line(504, 228, 552, 228); s.label(528, 208, "검색")
    s.line(672, 228, 752, 228, "accent"); s.label(712, 208, "즉시 반영", ACCENT)
    # branch
    s.line(612, 256, 612, 300)
    s.arrow("M 708,332 H 792 Q 800,332 800,324 V 256"); s.label(752, 312, "아니요 · 유지")
    s.line(612, 364, 612, 400); s.label(640, 376, "예")
    s.line(688, 432, 816, 432); s.label(752, 412, "제약 검증 통과")
    s.line(888, 404, 888, 256, dashed=True); s.label(936, 320, "판단 갱신")
    # nodes
    s.node(40, 200, 128, 56, "확정 발화", "화자 · 신뢰도 · 시각", "input", "", shape="oval")
    s.node(216, 200, 120, 56, "L0 다듬기", "규정 팩 용어로 맞춤", "step", "L0")
    s.node(384, 200, 120, 56, "L1 규칙", "요건 · 표현 · 수치", "step", "L1")
    s.node(552, 200, 120, 56, "L2 검색", "낱자 조각 · 의미 유사도", "step", "L2")
    s.node(752, 200, 208, 56, "화면 반영", "판정 · 경보 · 안내 카드", "step", "OUT")
    s.diamond(612, 332, 96, 32, "재판정 필요?", "부분 충족 · 의심")
    s.node(536, 400, 152, 64, "L3 재판정", "LLM · 허용 후보만 · 시간 예산", "focal", "L3")
    s.node(816, 404, 144, 56, "결과 기록·연결", "앞선 판단을 대체", "store", "LOG")
    s.legend([("focal", "LLM 판정"), ("step", "규칙·검색 단계"), ("store", "기록"), ("accent", "즉시 반영 경로"), ("default", "흐름"), ("dashed", "뒤늦게 도착하는 갱신")])
    return s


def d03_correction() -> Svg:
    s = Svg("03-correction", "받아쓴 문장 교정 · 원문을 보존하는 제한적 보완", "받아쓴 문장이 규정 팩 용어로 보완되고, 재판정 경로에서만 선택적으로 언어 모델이 허용 후보 안에서 용어 조합을 고르며, 검사에 실패하면 원래 해석으로 진행하는 흐름", 1000, 400)
    s.dy = -152
    s.line(176, 228, 224, 228); s.label(200, 208, "다듬기")
    s.line(360, 228, 408, 228); s.label(384, 208, "후보")
    s.line(544, 228, 588, 228)
    s.line(732, 228, 816, 228); s.label(772, 208, "아니요 · 현재 해석")
    s.line(660, 260, 660, 300); s.label(688, 272, "예")
    s.line(660, 356, 660, 384)
    s.arrow("M 732,404 H 864 Q 872,404 872,396 V 256"); s.label(800, 384, "허용 조합 반영")
    s.arrow("M 732,428 H 896 Q 904,428 904,420 V 256", dashed=True); s.label(800, 436, "범위 밖·실패 → 원 해석")
    s.arrow("M 108,256 V 412 Q 108,420 116,420 H 224", dashed=True); s.label(148, 332, "원본 보존")
    s.node(40, 200, 136, 56, "확정 은행원 발화", "받아쓴 그대로", "input", "", shape="oval")
    s.node(224, 200, 136, 56, "규칙 보완", "규정 팩 용어 · 띄어쓰기", "step", "RULE")
    s.node(408, 200, 136, 56, "후보 선별", "모호한 낱말 · 용어 짝", "step", "SCOPE")
    s.diamond(660, 228, 72, 32, "보조 교정 사용?", "선택 연결점")
    s.node(588, 300, 144, 56, "교정 에이전트", "LLM · 허용 후보 조합 선택", "focal", "LLM")
    s.node(588, 384, 144, 64, "조합 재검사", "허용 후보인지 · 짝이 맞는지", "step", "CHECK")
    s.node(816, 200, 144, 56, "재판정 입력", "판정에 쓸 해석", "step", "JUDGE")
    s.node(224, 392, 136, 56, "확정 발화 기록", "원문 · 수치 그대로", "store", "DB")
    s.legend([("focal", "LLM (선택)"), ("step", "규칙·검사 단계"), ("store", "저장"), ("default", "흐름"), ("dashed", "보존 · 우회")])
    return s


def d04_rulepack() -> Svg:
    s = Svg("04-rulepack", "규정 팩 구축 · 원문에서 승인된 기준까지", "공개 규정 문서가 구조 추출, 후보 생성, 근거 대조, 사람 검수를 거쳐 버전이 고정된 규정 팩으로 발행되고, 상담 중에는 그 팩을 읽기만 하는 흐름", 1000, 480)
    s.dy = -64
    s.zone(212, 108, 768, 212, "상담 전 · 규정 분석과 사람 검수")
    s.zone(404, 332, 380, 104, "상담 중 · 읽기 전용")
    s.line(184, 176, 232, 176); s.label(208, 156, "PDF")
    s.line(376, 176, 424, 176); s.label(400, 156, "구조화")
    s.line(568, 176, 616, 176); s.label(592, 156, "후보")
    s.line(760, 176, 808, 176, "accent"); s.label(784, 156, "검수 요청", ACCENT)
    s.line(688, 208, 688, 248, dashed=True)
    s.line(884, 208, 884, 352); s.label(920, 272, "발행")
    s.line(808, 384, 760, 384); s.label(784, 364, "불러오기")
    s.line(616, 384, 568, 384); s.label(592, 364, "조회")
    s.node(40, 144, 144, 64, "원천 문서", "법령 · 약관 · 상품설명서", "input", "SRC")
    s.node(232, 144, 144, 64, "구조 추출", "표 · 제목 계층 복원", "step", "PARSE")
    s.node(424, 144, 144, 64, "후보 생성", "언어 모델 추출", "step", "DRAFT")
    s.node(616, 144, 144, 64, "근거 대조", "구절 · 페이지 · 좌표", "focal", "CHECK")
    s.node(808, 144, 152, 64, "사람 검수·승인", "검토 대기열 · 승인 서명", "step", "REVIEW")
    s.node(616, 248, 144, 48, "자동 폐기", "근거 없는 항목", "optional", "")
    s.node(808, 352, 152, 64, "발행된 규정 팩", "버전 고정 · 불변", "store", "PACK")
    s.node(616, 352, 144, 64, "저장·색인", "빠르게 찾도록 정리", "store", "DB")
    s.node(424, 352, 144, 64, "상담 진행", "그 상담의 판단 기준", "step", "RUN")
    s.legend([("focal", "근거 검증"), ("step", "처리 단계"), ("store", "산출물 · 저장"), ("optional", "자동 폐기"), ("accent", "검수 대기"), ("default", "흐름")])
    return s


def d05_userflow() -> Svg:
    s = Svg("05-userflow", "상담원의 사용 흐름 · 접속에서 종료 기록까지", "상담원이 접속해 규정 기준을 확인하고 상담을 진행하는 동안 안내·경보를 근거 원문으로 확인해 설명을 보완하며, 종료 후 리포트를 남기는 흐름", 1000, 352)
    s.dy = -104
    s.line(168, 180, 216, 180); s.label(192, 160, "시작")
    s.line(360, 180, 408, 180); s.label(384, 160, "기준 확인")
    s.line(584, 180, 632, 180); s.label(608, 160, "종료")
    s.line(768, 180, 816, 180); s.label(792, 160, "기록")
    s.line(464, 216, 464, 296, "accent"); s.label(520, 248, "경보 · 안내 발생", ACCENT)
    s.line(536, 324, 592, 324); s.label(564, 304, "근거 보기")
    s.line(736, 324, 792, 324); s.label(764, 304, "보완 설명")
    s.arrow("M 876,296 V 256 Q 876,248 868,248 H 552 Q 544,248 544,240 V 216", dashed=True); s.label(700, 228, "상담 계속")
    s.node(40, 152, 128, 56, "접속", "설치 없이 브라우저로", "input", "", shape="oval")
    s.node(216, 152, 144, 64, "상담 준비", "규정 팩 · 필수 안내 · 서류", "step", "01")
    s.node(408, 152, 176, 64, "상담 진행", "녹음 또는 텍스트 · 실시간 전사", "focal", "02")
    s.node(632, 152, 136, 64, "상담 종료", "종료 버튼 한 번", "step", "03")
    s.node(816, 152, 144, 64, "종료 리포트", "항목별 기록 · PDF 저장", "step", "04")
    s.node(392, 296, 144, 56, "안내·경보 확인", "미고지 · 수치 · 금지 표현", "step", "A")
    s.node(592, 296, 144, 56, "근거 원문", "형광펜 · 주변 문맥 · 페이지", "step", "B")
    s.node(792, 296, 168, 56, "설명 보완·조치 기록", "고지 기록 · 제외 · 확인", "step", "C")
    s.legend([("focal", "상담 화면"), ("step", "화면 · 행동"), ("input", "진입"), ("accent", "확인 필요"), ("default", "흐름"), ("dashed", "반복 (상담 중 여러 번)")])
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
