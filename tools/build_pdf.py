#!/usr/bin/env python3
"""마크다운 원본 -> 인쇄용 PDF

왜 브라우저를 쓰나
    표가 많은 한국어 문서를 PDF 로 만들려면 조판 엔진이 필요하다.
    Chrome 헤드리스는 이미 설치돼 있고, 화면용 HTML 과 같은 렌더러를 재사용할 수 있으며,
    텍스트가 살아 있는 PDF(래스터 아님)를 만든다. pandoc·weasyprint 는 추가 설치가 필요하다.

사용
    python build_pdf.py                          기본: 핵심기획안.md -> 핵심기획안.pdf
    python build_pdf.py <입력.md> <출력.pdf>
"""

import io, os, subprocess, sys, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mdfigure import inline_figures

sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME_CANDIDATES = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
]

FONTS = ('https://fonts.googleapis.com/css2'
         '?family=IBM+Plex+Sans+KR:wght@400;500;600'
         '&family=IBM+Plex+Mono:wght@400;500&display=swap')

HEAD = '''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<link rel="stylesheet" href="''' + FONTS + '''">
<style>
@page { size: A4; margin: 20mm 17mm 17mm; }

:root{
  --ink:#15242B; --ink-2:#43555C; --ink-3:#7A8B91;
  --rule:#D8E0DF; --rule-strong:#A8B7B6;
  --teal:#0F6055; --seal:#AF3A20;
  --wash:#F3F7F6;
  --f-body:"IBM Plex Sans KR","Malgun Gothic","Apple SD Gothic Neo",sans-serif;
  --f-mono:"IBM Plex Mono",Consolas,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:var(--f-body); color:var(--ink);
  font-size:10.2pt; line-height:1.58;
  -webkit-print-color-adjust:exact; print-color-adjust:exact;
}

/* ---------- 표지 ---------- */
.cover{height:247mm;display:flex;flex-direction:column;justify-content:center;break-after:page}
.cover .eyebrow{font-family:var(--f-mono);font-size:8.5pt;letter-spacing:.18em;color:var(--ink-3);margin-bottom:10mm}
.cover h1{font-size:30pt;font-weight:600;letter-spacing:-.02em;line-height:1.2;margin:0 0 6mm;text-wrap:balance}
.cover .sub{font-size:12pt;color:var(--ink-2);margin:0 0 16mm;max-width:120mm;line-height:1.6}
.cover .meta{border-top:1.2pt solid var(--rule-strong);padding-top:5mm;display:grid;grid-template-columns:28mm 1fr;gap:2.4mm 6mm;font-size:9.5pt}
.cover .meta dt{font-family:var(--f-mono);font-size:8pt;letter-spacing:.1em;color:var(--ink-3);margin:0}
.cover .meta dd{margin:0;color:var(--ink-2)}

/* ---------- 목차 ---------- */
.toc{break-after:page}
.toc h2{font-size:15pt;font-weight:600;margin:0 0 6mm;padding:0;border:0}
.toc ol{list-style:none;margin:0;padding:0;column-count:2;column-gap:10mm}
.toc li{font-size:9.5pt;line-height:1.75;break-inside:avoid;display:flex;gap:3mm}
.toc .n{font-family:var(--f-mono);font-size:8.5pt;color:var(--teal);min-width:9mm;flex-shrink:0}

/* ---------- 본문 ---------- */
h1{font-size:20pt;font-weight:600;margin:0 0 5mm}
h2{
  font-size:15pt;font-weight:600;letter-spacing:-.01em;line-height:1.3;
  margin:0 0 5mm;padding-bottom:2.5mm;border-bottom:1.2pt solid var(--rule-strong);
  break-before:page;break-after:avoid;text-wrap:balance;
}
h2:first-of-type{break-before:auto}
h3{font-size:11.5pt;font-weight:600;margin:7mm 0 2.5mm;break-after:avoid;color:var(--ink)}
h4{font-size:10.2pt;font-weight:600;margin:5mm 0 2mm;break-after:avoid;color:var(--ink-2)}

p{margin:0 0 3mm;orphans:2;widows:2}
strong{font-weight:600}
a{color:var(--teal);text-decoration:none}

ul,ol{margin:0 0 3.5mm;padding-left:5.5mm}
li{margin-bottom:1.2mm;orphans:2;widows:2}
ol li::marker{font-family:var(--f-mono);font-size:.9em;color:var(--teal)}

blockquote{
  margin:0 0 4mm;padding:2.5mm 0 2.5mm 4mm;
  border-left:1.5pt solid var(--teal);color:var(--ink-2);font-size:9.6pt;
  break-inside:avoid;
}
blockquote p{margin:0 0 1.5mm}
blockquote p:last-child{margin:0}

hr{display:none}

/* ---------- 표 ---------- */
.tw{margin:0 0 4.5mm;break-inside:auto}
table{border-collapse:collapse;width:100%;font-size:8.8pt;line-height:1.45}
thead{display:table-header-group}
thead th{
  text-align:left;font-weight:600;font-size:7.8pt;letter-spacing:.03em;
  text-transform:uppercase;color:var(--ink-2);background:var(--wash);
  padding:1.8mm 2.2mm;border-top:1.2pt solid var(--rule-strong);
  border-bottom:.8pt solid var(--rule-strong);
}
tbody td{
  padding:1.8mm 2.2mm;border-bottom:.5pt solid var(--rule);
  vertical-align:top;color:var(--ink-2);
  font-variant-numeric:tabular-nums;
}
tbody tr{break-inside:avoid}
tbody td:first-child{color:var(--ink);font-weight:500}
tbody td strong{color:var(--ink)}

/* ---------- 코드 ---------- */
code{font-family:var(--f-mono);font-size:.88em;background:var(--wash);padding:.3mm .8mm;border-radius:.5mm}
pre{
  margin:0 0 4mm;padding:3mm 3.5mm;background:var(--wash);
  border-left:1.5pt solid var(--teal);font-size:8.2pt;line-height:1.5;
  break-inside:avoid;overflow:visible;white-space:pre-wrap;
}
pre code{background:none;padding:0;font-size:inherit;color:var(--ink-2)}

/* ---------- 도해 ---------- */
.dia{margin:5mm 0 6mm;break-inside:avoid;text-align:center}
.dia svg{width:100%;max-width:170mm;height:auto;display:block;margin:0 auto}
.dia figcaption{margin:3mm auto 0;font-size:8.6pt;line-height:1.55;color:var(--ink-2);text-align:left;max-width:170mm}
.dia figcaption b{color:var(--ink)}

/* ---------- 칩 ---------- */
.chip{font-family:var(--f-mono);font-size:7.5pt;font-weight:500;letter-spacing:.04em;padding:.3mm 1.2mm;border-radius:.5mm;white-space:nowrap}
.chip-verify{background:#F9EBE6;color:var(--seal);border:.5pt solid var(--seal)}
.chip-decide{background:#E7F2EF;color:var(--teal);border:.5pt solid var(--teal)}
.chip-form{color:var(--ink-3);border:.5pt solid var(--rule-strong);font-size:7pt;margin-left:1mm}
</style>
</head>
<body>
<div class="cover">
  <p class="eyebrow">__EYEBROW__</p>
  <h1>__H1__</h1>
  <p class="sub">__SUB__</p>
  <dl class="meta">__META__</dl>
</div>
<nav class="toc"><h2>목차</h2><ol id="toclist"></ol></nav>
<article id="doc"></article>
<script id="src" type="text/markdown">
'''

TAIL = '''</script>
<script>
(function () {
  var src = document.getElementById('src').textContent;

  function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  // 백틱으로 먼저 쪼개 코드 스팬이 굵게·링크 치환에 오염되지 않게 한다
  function inline(raw) {
    var parts = esc(raw).split('`'), acc = '';
    for (var k = 0; k < parts.length; k++) {
      if (k % 2 === 1) {
        var c = parts[k];
        if (c === '[확인]') acc += '<span class="chip chip-verify">확인 필요</span>';
        else if (c === '[결정]') acc += '<span class="chip chip-decide">결정 필요</span>';
        else acc += '<code>' + c + '</code>';
      } else {
        acc += parts[k]
          .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
          .replace(/\\[([^\\]\\[]+)\\]\\((https?:[^)]+)\\)/g, '<a href="$2">$1</a>')
          .replace(/\\[(첨부[\\d\\-,\\s가-힣]{1,24})\\]/g, '<span class="chip chip-form">$1</span>');
      }
    }
    return acc;
  }

  function headNum(t) {
    var m = t.match(/^(\\d+(?:\\.\\d+)*\\.?)\\s+([\\s\\S]*)$/);
    return m ? { n: m[1], rest: m[2] } : { n: '', rest: t };
  }

  var lines = src.replace(/\\r\\n/g, '\\n').split('\\n');
  var out = [], i = 0, para = [], list = null, quote = [];

  function fp(){ if(para.length){ out.push('<p>'+inline(para.join(' '))+'</p>'); para=[]; } }
  function fl(){ if(list){ out.push('<'+list.tag+'>'+list.items.map(function(x){return '<li>'+x+'</li>';}).join('')+'</'+list.tag+'>'); list=null; } }
  function fq(){ if(quote.length){ out.push('<blockquote>'+quote.map(function(q){return '<p>'+inline(q)+'</p>';}).join('')+'</blockquote>'); quote=[]; } }
  function fa(){ fp(); fl(); fq(); }

  while (i < lines.length) {
    var ln = lines[i];

    // 도해 figure 블록은 원문 그대로 내보낸다 (빌더가 만든 신뢰된 HTML)
    if (/^<figure/.test(ln)) {
      fa(); var fb=[];
      while (i < lines.length && !/^<\\/figure>/.test(lines[i])) { fb.push(lines[i]); i++; }
      if (i < lines.length) { fb.push(lines[i]); i++; }
      out.push(fb.join('\\n')); continue;
    }

    if (/^```/.test(ln)) {
      fa(); var buf=[]; i++;
      while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i++; }
      i++; out.push('<pre><code>'+esc(buf.join('\\n'))+'</code></pre>'); continue;
    }

    if (/^\\s*\\|/.test(ln)) {
      fa(); var rows=[];
      while (i < lines.length && /^\\s*\\|/.test(lines[i])) {
        rows.push(lines[i].trim().replace(/^\\||\\|$/g,'').split('|').map(function(c){return c.trim();}));
        i++;
      }
      var head=null, body=rows;
      if (rows.length>1 && rows[1].every(function(c){return /^:?-{2,}:?$/.test(c.replace(/\\s/g,''));})) {
        head=rows[0]; body=rows.slice(2);
      }
      var t='<div class="tw"><table>';
      if(head) t+='<thead><tr>'+head.map(function(c){return '<th>'+inline(c)+'</th>';}).join('')+'</tr></thead>';
      t+='<tbody>'+body.map(function(r){return '<tr>'+r.map(function(c){return '<td>'+inline(c)+'</td>';}).join('')+'</tr>';}).join('')+'</tbody></table></div>';
      out.push(t); continue;
    }

    var h = ln.match(/^(#{1,4})\\s+(.*)$/);
    if (h) {
      fa();
      var lvl=h[1].length, parts=headNum(h[2]);
      if (lvl===1) out.push('<h1>'+inline(h[2])+'</h1>');
      else if (lvl===2) out.push('<h2>'+inline(h[2])+'</h2>');
      else if (lvl===3) out.push('<h3>'+inline(h[2])+'</h3>');
      else out.push('<h4>'+inline(h[2])+'</h4>');
      i++; continue;
    }

    var q = ln.match(/^>\\s?(.*)$/);
    if (q) { fp(); fl(); quote.push(q[1]); i++; continue; }

    if (/^\\s*---+\\s*$/.test(ln)) { fa(); i++; continue; }

    var ul = ln.match(/^[-*]\\s+(.*)$/), ol = ln.match(/^(\\d+)\\.\\s+(.*)$/);
    if (ul || ol) {
      fp(); fq();
      var tag = ul ? 'ul' : 'ol';
      if (!list || list.tag !== tag) { fl(); list = { tag: tag, items: [] }; }
      list.items.push(inline(ul ? ul[1] : ol[2]));
      i++; continue;
    }

    if (list && /^\\s{2,}\\S/.test(ln)) {
      list.items[list.items.length-1] += '<br>' + inline(ln.trim());
      i++; continue;
    }

    if (!ln.trim()) { fp(); fq(); i++; continue; }

    fl(); fq(); para.push(ln.trim()); i++;
  }
  fa();

  var doc = document.getElementById('doc');
  doc.innerHTML = out.join('\\n');

  // 표지에 이미 제목이 있으므로 본문 h1 과 그 직후 메타 인용은 제거한다
  var h1 = doc.querySelector('h1');
  if (h1) {
    var nx = h1.nextElementSibling;
    h1.remove();
    if (nx && nx.tagName === 'BLOCKQUOTE') nx.remove();
  }

  var toc = document.getElementById('toclist');
  doc.querySelectorAll('h2').forEach(function (el) {
    // 칩(확인 필요·결정 필요·첨부 태그)은 목차 라벨에서 뺀다
    var clone = el.cloneNode(true);
    clone.querySelectorAll('.chip').forEach(function (c) { c.remove(); });
    var text = clone.textContent.trim();
    var p = text.match(/^(\\d+(?:\\.\\d+)*\\.?|부록\\s*[A-Z]\\.)\\s+([\\s\\S]*)$/);
    var num = p ? p[1].replace(/\\.$/, '') : '';
    var label = p ? p[2] : text;
    var li = document.createElement('li');
    li.innerHTML = '<span class="n">' + num + '</span><span>' + label + '</span>';
    toc.appendChild(li);
  });
})();
</script>
</body>
</html>
'''


def find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def build(md_path, pdf_path, title, eyebrow, h1, sub, meta):
    md = io.open(md_path, encoding='utf-8').read()
    md, missing = inline_figures(md, os.path.dirname(os.path.abspath(md_path)))
    for m in missing:
        print(f'  경고: 도해 파일 없음 {m}')
    metahtml = ''.join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in meta)
    head = (HEAD.replace('__TITLE__', title).replace('__EYEBROW__', eyebrow)
                .replace('__H1__', h1).replace('__SUB__', sub).replace('__META__', metahtml))
    html = head + md + TAIL

    tmpdir = tempfile.mkdtemp(prefix='faic_pdf_')
    tmphtml = os.path.join(tmpdir, 'print.html')
    io.open(tmphtml, 'w', encoding='utf-8', newline='\n').write(html)

    chrome = find_chrome()
    if not chrome:
        raise SystemExit('Chrome/Edge 를 찾지 못했습니다')

    out_abs = os.path.abspath(pdf_path)
    cmd = [chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
           '--no-pdf-header-footer', '--virtual-time-budget=20000',
           '--print-to-pdf=' + out_abs,
           'file:///' + tmphtml.replace('\\', '/')]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=240)
    shutil.rmtree(tmpdir, ignore_errors=True)

    if not os.path.exists(out_abs):
        print(r.stdout[-1500:]); print(r.stderr[-1500:])
        raise SystemExit('PDF 생성 실패')
    return out_abs



def _md_version(src):
    """md 첫 줄 제목의 vX.Y 를 표지에 그대로 쓴다. 하드코딩하면 개정 때마다 어긋난다."""
    import re
    line = open(src, encoding='utf-8').readline()
    m = re.search(r'v\d+\.\d+', line)
    return m.group(0) if m else ''


def _md_date(src):
    import re
    with open(src, encoding='utf-8') as f:
        head = f.read(600)
    m = re.search(r'\*\*갱신\*\*\s*(\d{4}-\d{2}-\d{2})', head)
    return m.group(1) if m else ''


if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'docs', '기획', '핵심기획안.md')
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'docs', '기획', '핵심기획안.pdf')
    p = build(
        src, dst,
        title='말틈 핵심 기획안',
        eyebrow='2026 금융 AI CHALLENGE',
        h1='말틈<br>핵심 기획안',
        sub='창구 상담의 설명의무 이행을 실시간으로 확인하는 AI 컴플라이언스 에이전트. '
            '팀 내부 공유 문서이며 제출 문서(기획서·기능명세서)의 원본이다.',
        meta=[('버전', _md_version(src)),
              ('작성', _md_date(src)),
              ('마감', '2026-09-07 (월) 10:00'),
              ('접속 의무', '2026-09-07 11:00 ~ 09-11 23:59'),
              ('원본', '핵심기획안.md')],
    )
    size = os.path.getsize(p)
    print(f'생성 완료: {p}  {size:,} bytes')
    try:
        import pymupdf
        d = pymupdf.open(p)
        chars = sum(len(pg.get_text()) for pg in d)
        print(f'  {d.page_count} 페이지 · 추출 텍스트 {chars:,}자')
    except Exception:
        pass
