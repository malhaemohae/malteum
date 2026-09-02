"""마크다운의 SVG 참조를 인라인 figure 로 바꾼다.

    ![캡션](도해/1_전체구성.svg)
      ->
    <figure class="dia">
    ...svg...
    <figcaption>캡션</figcaption>
    </figure>

빌더(build_pdf.py · build_html.py)가 HTML 을 조립하기 전에 이 치환을 한다.
치환 결과는 `<figure` 로 시작하고 `</figure>` 로 끝나는 블록이므로,
브라우저 쪽 마크다운 렌더러의 HTML 통과 규칙이 그대로 내보낸다.
"""

import io, os, re

PAT = re.compile(r'^!\[([^\]]*)\]\(([^)]+\.svg)\)\s*$', re.M)


def inline_figures(md, base_dir):
    """base_dir 기준으로 svg 파일을 읽어 figure 블록으로 치환. 없는 파일은 그대로 둔다."""
    missing = []

    def sub(m):
        cap, rel = m.group(1), m.group(2)
        path = os.path.join(base_dir, rel.replace('/', os.sep))
        if not os.path.exists(path):
            missing.append(rel)
            return m.group(0)
        svg = io.open(path, encoding='utf-8').read().strip()
        # 인라인이므로 고정 width/height 를 떼고 CSS 가 크기를 잡게 한다
        svg = re.sub(r'\s(?:width|height)="\d+"', '', svg, count=2)
        # figcaption 은 마크다운 렌더러를 거치지 않으므로 굵게·코드 표기를 여기서 처리한다
        c = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', cap)
        c = re.sub(r'`([^`]+)`', r'<code>\1</code>', c)
        cap_html = f'<figcaption>{c}</figcaption>' if c else ''
        return f'<figure class="dia">\n{svg}\n{cap_html}\n</figure>'

    out = PAT.sub(sub, md)
    return out, missing
