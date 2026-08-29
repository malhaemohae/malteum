# tools/

기획 문서를 배포 형태로 빌드하는 스크립트. 기획안 18장(확정 결정 요약)의 "마크다운 → PDF 자동 빌드" 항목이 가리키는 곳이다.

## build_pdf.py

`docs/기획/핵심기획안.md` 를 `핵심기획안.pdf` 로 조판한다. 인자를 주면 다른 파일도 된다.

```bash
python tools/build_pdf.py                                  # 기본 경로
python tools/build_pdf.py <입력.md> <출력.pdf>
```

- **Chrome 헤드리스**(화면 없이 백그라운드로 도는 크롬)로 HTML 을 조판한 뒤 인쇄해 PDF 를 뽑는다. 표가 많은 한국어 문서에서 텍스트가 살아 있는 PDF 가 나온다. Chrome 또는 Edge 가 설치돼 있어야 한다.
- 웹폰트를 Google Fonts 에서 받으므로 네트워크가 필요하다.
- `mdfigure.py` 가 같은 폴더에 있어야 한다.

## mdfigure.py

마크다운의 `![캡션](도해/1_전체구성.svg)` 참조를 실제 SVG 내용으로 치환한다. 빌더가 HTML 을 조립하기 전에 부른다.

**md 와 SVG 는 각각 별개의 원본이다.** md 안의 모듈 이름을 고쳐도 도해 SVG 안의 라벨은 그대로 남고, PDF 에는 둘 다 들어간다. 문서를 고칠 때 `docs/기획/도해/*.svg` 도 함께 봐야 하는 이유다.

## PDF 재생성 시 주의

같은 md 로 다시 만들어도 **바이너리가 매번 달라진다.** PDF 안에 생성 시각이 들어가기 때문이다. 내용은 동일하다.

그래서 `git status` 에 PDF 가 잡혔다고 해서 내용이 바뀐 것은 아니다. 내용 변화 여부는 텍스트를 뽑아 비교한다.

```bash
git show HEAD:docs/기획/핵심기획안.pdf > /tmp/a.pdf
pdftotext -layout -enc UTF-8 /tmp/a.pdf /tmp/a.txt
pdftotext -layout -enc UTF-8 docs/기획/핵심기획안.pdf /tmp/b.txt
diff /tmp/a.txt /tmp/b.txt
```

차이가 없으면 `git checkout -- docs/기획/핵심기획안.pdf` 로 되돌린다. 의미 없는 1MB 바이너리 변경을 커밋에 남기지 않는다.
