"""Build editable, self-contained submission documents from reviewed content."""
from pathlib import Path
import base64
import html
import json
import re

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'assets'

def e(s):
    return html.escape(str(s))

def bullets(*items):
    return '<ul>' + ''.join(f'<li>{s}</li>' for s in items) + '</ul>'

def table(headers, rows, widths=None):
    col = '' if not widths else '<colgroup>' + ''.join(f'<col style="width:{w}%">' for w in widths) + '</colgroup>'
    return '<table>' + col + '<thead><tr>' + ''.join(f'<th>{x}</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{x}</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table>'

def h(text):
    return f'<h3>{text}</h3>'

def note(text, pending=False):
    return f'<aside class="{"pending" if pending else "note"}">{text}</aside>'

def source(text):
    return f'<p class="source">{text}</p>'

def figure(slug, caption, diagram=False, placeholder=None):
    folder = ASSETS / ('diagrams' if diagram else 'screens')
    p = folder / f'{slug}.png'
    if diagram and p.exists():
        uri = 'data:image/png;base64,' + base64.b64encode(p.read_bytes()).decode()
        body = f'<img src="{uri}" alt="{e(caption)}" data-asset="{e(slug)}">'
    else:
        body = f'<div class="placeholder" data-asset="{e(slug)}"><b>{"도식 삽입 대기" if diagram else "화면 삽입 예정 · 촬영 안내"}</b><p>{e(placeholder or caption)}</p><small>실서버 배포 후 캡처 · 핵심 영역은 빨간 박스로 강조 · 개인정보와 접속 비밀 제외</small></div>'
    return f'<figure class="{"diagram" if diagram else "screen"}" contenteditable="false">{body}<figcaption contenteditable="true">{caption}</figcaption></figure>'

FSC = '<a href="https://fsc.go.kr/po0201101/76243">금융위원회, 금융상품 설명의무의 합리적 이행을 위한 가이드라인(2021)</a>'
RULES = '<a href="https://daker.ai/public/hackathons/2026-finance-ai-challenge">2026 금융 AI Challenge 공식 요강</a>'

PROPOSAL = [
('1. 서비스 명칭',
 '<div class="hero"><p class="eyebrow">금융상품 대면 상담 지원 AI</p><h1>말틈</h1><p class="lead">상담 중 놓친 설명을 짚고,<br>판단의 근거를 실제 문서에서 보여주는 서비스</p></div>'
 + '<h2>2. 아이디어 기획 핵심내용(요약)</h2>'
 + bullets('<b>대상</b>: 은행 영업점 창구 직원. 특히 상품 규정과 설명 절차를 익히는 신규 직원의 상담 지원',
 '<b>해결 과제</b>: 필수 안내의 누락, 잘못 말한 수치, 단정적인 표현, 고객의 위험 신호를 상담 중 확인하기 어려운 문제',
 '<b>핵심 동작</b>: 상담 음성 → 발화·화자 확인 → 승인된 룰팩 대조 → 보완 안내와 PDF 근거 표시 → 종료 리포트',
 '<b>차별적 경험</b>: 경보의 이유를 인용문과 형광펜 표시로 확인하고, 같은 원문의 주변 문맥까지 탐색 가능',
 '<b>현재 MVP</b>: 정기예금·가계 신용대출의 사전 구축 룰팩, 상담 지원 화면, 근거 탐색, 저장 기록과 리포트 연결 구현')
 + note('고객에게 추가 앱 설치를 요구하지 않고 상담원의 기존 설명을 지원하는 방식. 금융소비자의 상품 이해를 돕는 것을 목표로 함.' )),
('3. 문제 정의 및 제안 배경',
 h('상담 현장에서 생기는 세 가지 공백')
 + table(['문제','상담에서 발생하는 상황','말틈의 대응'],[
 ('설명 누락','상품의 핵심 조건을 설명했더라도 일부 요건이 빠질 수 있음','항목별 충족·부분 충족·미고지를 구분해 다음 설명 지원'),
 ('근거 확인의 단절','직원이 설명서를 다시 찾는 동안 상담 흐름이 끊김','해당 원문 위치와 주변 문맥을 화면에서 바로 확인'),
 ('사후 확인 비용','녹음만으로는 언제 무엇을 설명했는지 다시 찾아야 함','발화·판정·근거·사람의 조치를 연결한 기록 제공')],[19,40,41])
 + h('고객과 채널 선택의 이유')
 + bullets('직접 이용자: 영업점 창구 직원. 규정 확인과 고객 설명을 동시에 수행하는 상황에 집중',
 '수혜 고객: 대면 설명이 필요한 금융소비자. 특히 용어를 다시 물어보거나 설명 속도를 조절해야 하는 고객의 이해 지원',
 '첫 적용 범위: 정기예금과 가계 신용대출. 수치·권리·비용·주의사항을 함께 설명하는 상담을 검증 대상으로 선정')
 + h('현장 인터뷰를 통한 요구 확인')
 + bullets('새마을금고 재직자 1인을 대상으로 2회 인터뷰 진행. 규정 질의, 신규 직원 지원, 중도해지 설명과 서류 확인의 필요성을 파악했음',
 '직원의 상담 화면과 고객에게 전달할 설명을 구분하고, 근거를 먼저 확인할 수 있는 흐름에 반영했음',
 '표본이 1명·1개 지점이므로 금융권 전체의 수요나 효용을 입증한 결과로 일반화하지 않음')
 + source('문제 배경: '+FSC+' · 현장 근거: 팀 내부 「현장검증 인터뷰정리」(2026-08-26). 인터뷰는 제품 요구 도출 자료이며 통계적 효과 검증 자료가 아님.')),
('4. 서비스 컨셉 및 차별성',
 '<p class="lead small">규정을 읽는 도구에서,<br>현재 상담의 설명과 근거를 함께 확인하는 도구로</p>'
 + table(['비교 관점','일반적인 접근 방식','말틈의 설계'],[
 ('지원 시점','상담 후 녹음 청취·요약','상담 중 보완할 항목을 제시하고 종료 기록까지 연결'),
 ('판단 기준','직원의 기억 또는 수동 체크리스트','원문 근거와 버전을 가진 룰팩의 항목·요건으로 대조'),
 ('답변 확인','답변 문장이나 검색 결과 목록 확인','인용 위치의 PDF 형광펜과 주변 페이지를 직접 확인'),
 ('수치 처리','유창한 답변 과정에서 수치가 바뀔 위험','발화 수치를 보존하고 기준 수치와 불일치 경보 표시'),
 ('최종 판단','자동 판단을 그대로 받아들일 위험','근거 확인과 실제 보완 설명, 사람의 조치를 기록')],[18,39,43])
 + source('비교 대상은 접근 방식의 차이이며, 특정 경쟁 제품 전체의 기능 부재를 주장하는 표가 아님.')
 + h('핵심 사용 장면')
 + bullets('상담원이 세율이나 기한을 잘못 말하면 발화값과 룰팩 기준값을 비교해 확인할 지점을 제시',
 '경보에서 근거를 열면 실제 문서의 해당 위치를 확인. 예외·조건 확인이 필요하면 주변 문맥과 다른 페이지까지 탐색',
 '상담원이 근거를 확인하고 다시 설명한 뒤, 종료 리포트에서 관련 발화와 조치 이력을 확인')
 + note('AI가 안내문을 보여준 것과 고객에게 실제 설명한 것을 구분함. 리포트는 상담 지원 기록이며 법적 적합성이나 고객 이해의 완전한 증명이 아님.')),
('5. 활용 데이터 및 생성형 AI 모델 적용 방안',
 table(['데이터','확보·가공 방식','사용 목적'],[
 ('규정·상품 문서','공개 법령·약관·상품설명서 및 공식 상품 공시의 보관본','항목의 기준과 원문 인용 위치 제공'),
 ('룰팩','원문·페이지·좌표 검증과 검수 절차를 거친 버전별 JSON','필수 안내, 금지 취지, 위험 신호, 참고 정보의 대조 기준'),
 ('시연 상담','가상 고객·직원 대본과 합성 음원, 저장된 예시 이벤트','실제 고객 정보 없이 상담 흐름과 기대 결과 검증'),
 ('실행 중 입력','음성 또는 테스트 발화, 직원의 질문·조치','발화별 판정·근거 안내 및 세션 기록')],[21,43,36])
 + h('AI가 필요한 지점과 규칙으로 제한하는 지점')
 + bullets('<b>STT(Speech To Text: 음성의 문자 변환)</b>: 음성을 발화로 변환. 화자 분리·역할 추정으로 직원 설명과 고객 반응을 구분',
 '<b>검색</b>: 어휘·자모 유사도와 임베딩을 이용해 관련 규정 후보를 좁힘. 유사도 자체를 설명 완료로 해석하지 않음',
 '<b>LLM(Large Language Model: 대규모 언어 모델)</b>: 규칙만으로 판단하기 어려운 설명의 취지를 제한된 후보 안에서 재판정. 허용 항목·결과 형식을 검사한 뒤 반영',
 '<b>근거 기반 조력</b>: 팩에 연결된 승인 문장·인용을 우선 재사용. 팩 밖의 문서 본문 전체 검색은 현재 기본 연결에 포함되지 않음',
 '<b>수치 검증</b>: 명시적 값·단위는 규칙으로 대조. 잘못 말한 값을 모델이 정답으로 고쳐 오류 흔적을 지우지 않도록 설계')
 + note('MVP는 사전 구축된 기존 문서·룰팩을 사용함. 새 개정 문서 업로드부터 자동 갱신·배포까지 이어지는 사용자 기능은 이번 구현 범위에서 제외했음.')
 + source('데이터 근거: 저장소 원천 감사·파이프라인 문서 및 최신 계약 fixture. 금융기관과의 제휴·납품·공식 승인을 의미하지 않음.')),
('6. 기대 효과 및 확장 가능성',
 table(['대상','기대 효과','효과를 확인할 방법'],[
 ('금융소비자','누락된 안내와 어려운 용어에 대한 재설명을 받아 상품 조건을 이해하는 데 도움','상담 후 핵심 조건 이해도, 되물음 해결 여부 비교'),
 ('창구 직원','규정 탐색과 누락 점검을 지원받아 상담 설명에 집중','근거 탐색 시간, 누락 보완률, 경보 확인 부담 측정'),
 ('금융기관','상담 기준과 당시 설명의 연결 기록을 검토 가능','검토자의 재청취 시간, 근거 연결률, 오탐·미탐 분석')],[20,43,37])
 + note('위 효과는 검증할 가설임. 상담 시간 단축률·민원 감소율·매출 효과를 실측한 것으로 제시하지 않음.')
 + h('확장 순서')
 + bullets('<b>상품 확대</b>: 검수된 룰팩 추가를 통해 담보대출 등 다른 상담 유형으로 확장 검토. 현재 신용대출 구현과 구분',
 '<b>운영 체계</b>: 규정 개정 후보 탐지·비교·검수·승인 체계를 연결하되, 개정 문서가 즉시 상담 기준을 바꾸지 않도록 관리',
 '<b>기관 도입</b>: 기관 내부 문서와 내부망 모델을 연결하고 권한·보존·삭제 정책, 보안 검증을 도입 기관 기준에 맞춰 보강',
 '<b>인접 영역</b>: 보험·투자상품 설명 및 직원 교육에 적용 가능성을 검증한 뒤, 고지 절차가 있는 비금융 상담으로 확대 검토')
 + h('성능 개선 방향')
 + bullets('음성 전사 확정, 화자 역할 결정, 의미 재판정의 대기시간을 구분해 측정',
 '빠른 규칙 판정과 후속 의미 판정을 분리하되, 전체 음성 입력부터 화면 반영까지의 시간으로 체감 성능 확인',
 '모델별 실험 결과나 재생 타이밍 개선을 실운영 전체 지연 보장으로 환산하지 않음')),
('7. 검증 계획과 도입 전략',
 h('단계별 통과 기준')
 + table(['단계','확인할 질문','판단 근거'],[
 ('대회 MVP','심사자가 URL에서 상담·근거·리포트를 끝까지 확인할 수 있는가','배포 접속 점검, 예시 시연, PDF 근거 이동, 종료 리포트'),
 ('현장 파일럿','도움을 주는 경보가 상담 흐름을 방해하지 않는가','동일 대본 비교, 다양한 화자·잡음 조건, 직원 관찰·인터뷰'),
 ('기관 도입','보안과 책임 체계 안에서 안정적으로 운영 가능한가','접근 권한, 망 구성, 저장·삭제 정책, 모델 자원과 장애 대응')],[20,43,37])
 + h('평가 지표의 정의')
 + bullets('<b>누락 검출률</b>: 사람이 정답으로 표시한 누락 중 시스템이 찾아낸 비율',
 '<b>오탐 비율</b>: 시스템이 문제로 알린 항목 중 전문가가 문제없음으로 판정한 비율',
 '<b>근거 일치율</b>: 제시한 인용이 실제 문서에 있고 판단 내용도 뒷받침하는 비율',
 '<b>응답 지연</b>: 발화 종료부터 전사·첫 판정·후속 판정이 각각 화면에 표시되기까지의 시간',
 '<b>검증 방식</b>: 팩·모델·설정·대본 버전을 고정하고 정답 표본을 별도 관리. 기능 테스트 통과 수를 모델 정확도로 바꾸어 해석하지 않음')
 + note('파일럿 계획: 예금·대출 각 20건으로 정상·누락·수치 오류·금지 취지·위험 신호를 균형 구성하고 2인이 정답을 독립 검토. 초기 목표는 잘못된 인용 0건, 수치 오류 시험 전건 검출, 정상 시험의 잘못된 완료 판정 0건. 모두 미측정 목표이며 현장 지연 목표는 배포 실측 후 확정.')
 + h('팀 구성과 실행 책임')
 + table(['구성원','역할'],[('임한빈 · 팀장','기획·룰팩 구축·원문 근거 검증'),('노순혁','서버·세션·음성 처리 연결'),('서재오','프론트엔드·상담 화면 구현'),('허현준','판정 엔진·검색·LLM 연결')],[26,74])
 + source('근거 자료: 팀 내부 핵심기획안·현장 인터뷰·엔진 아키텍처·규정팩 감사 기록. 제출 형식과 운영 조건: '+RULES+'.')),
]

SPEC = [
('1. MVP 구현 범위',
 '<p class="lead small">기존 문서의 규정과 상담 발화를 연결하는<br>웹 기반 상담 지원 MVP</p>'
 + table(['구현 영역','현재 구현 내용'],[
 ('상담 준비','상품별 최신 룰팩 선택, 필수 안내·필요 서류 확인, 상담 입력 방식 선택'),
 ('상담 입력','마이크 입력, 텍스트 시험 입력, 예시 음원 재처리, 저장 기록 재생의 경로 구현'),
 ('상담 지원','발화 표시, 필수 항목 상태, 금지·수치·위험 경보, 쉬운 설명·규정 질의'),
 ('근거 탐색','PDF 해당 페이지·형광펜 표시, 확대와 페이지 이동, 출처 문서 연결'),
 ('기록과 리포트','상담 이력 조회, 저장 이벤트 재생, 항목별 기록·타임라인과 PDF 저장'),
 ('규정 조회','기존 룰팩 항목과 근거 문서 조회. 새 상담은 상품별 최신 버전만 노출')],[23,77])
 + h('현재 포함된 상담 기준')
 + table(['상품','팩 버전','항목 수'],[('ICBC 원화정기예금','DEP-2026.08-v6','12'),('하나은행 가계 신용대출','LOAN-2026.08-v7','15')],[44,38,18])
 + source('[실측] 2026-09-06 저장소 최신 계약 fixture의 items 배열을 직접 집계한 값. 전체 금융 규정의 포괄률을 의미하지 않음.')
 + bullets('새 상담은 선택한 팩 버전으로 유지하며, 과거 기록은 당시 적용한 버전을 기준으로 조회',
 '본 문서의 구현 범위는 저장소와 로컬 화면을 기준으로 함. 실서버 모델 연결 상태와 검증 절차는 5번에 별도 기재')
 + note('서비스명: 말틈 · 팀명: 말해모해<br>임한빈(팀장), 노순혁, 서재오, 허현준')),
('2. 주요 기능 목록',
 source('상태 구분: 구현 = 코드 경로 존재 · 로컬 확인 = 실제 로컬 화면 관찰 · 배포 확인 필요 = 홈서버에서 입력부터 결과까지 재확인 필요')
 + table(['기능명','기능 설명','관련 화면','구현 상태'],[
 ('상담 준비','최신 상품 팩과 필수 설명을 확인하고 상담 생성','상담 준비','구현'),
 ('음성 상담','마이크 음성을 서버에 전달하고 확정 발화를 수신','실시간 상담','구현 · 배포 확인 필요'),
 ('텍스트 시험','화자를 구분한 텍스트 입력으로 판정 경로 확인','테스트 입력','구현 · 모델 의존'),
 ('필수 안내 추적','설명 항목과 빠진 요건을 구분해 표시','필수 안내','구현'),
 ('경보 확인','수치 불일치·금지 표현·위험 신호 및 확인 기록','상담 안내','구현 · 모델 의존'),
 ('쉬운 말 안내','승인 문장 조회와 직전 발화 재설명 요청을 구분','쉬운 말·상담 가이드','구현'),
 ('규정 질의','팩에서 관련 항목과 연결된 근거 제시','규정 질문','구현 · 임베딩 의존'),
 ('근거 원문 탐색','형광펜 위치와 문서의 주변 문맥·페이지 확인','근거 원문','구현'),
 ('직원 수동 조치','설명 완료·해당 없음·경보 확인 등 조치 기록','필수 안내·경보','구현'),
 ('이력·기록 재생','종료 상담과 저장된 이벤트를 순서대로 조회','상담 이력','구현'),
 ('리포트·PDF','항목별 결과와 근거·타임라인 조회 및 저장','종료 리포트','구현'),
 ('규정·문서 조회','최신 팩 구성과 보관된 원문 문서를 조회','규정 팩·근거 문서','구현')],[19,44,18,19])
 + note('저장 기록 재생은 이미 기록된 결과를 보여주는 기능임. 새 음원을 STT·LLM으로 다시 처리하는 실행과 구분하여 검증해야 함.')),
('2. 주요 기능 목록',
 h('핵심 화면 A · 상담 전에 기준 확인')
 + figure('preparation-annotated','화면 1 삽입 위치. 상품·팩 버전·필수 안내를 강조할 예정.',placeholder='상담 시작 → 상담 준비. 상품 선택·팩 버전·필수 안내·상담 시작 버튼을 함께 촬영. 상품 선택과 시작 버튼에 빨간 박스 표시')
 + bullets('① 상품과 팩 버전을 확인한 뒤 필수 안내와 필요 서류 확인',
 '② 선택한 상품에 맞는 입력 경로로 상담 시작',
 '③ 새 상담에서 구버전이 함께 선택지로 나타나지 않는지 확인')
 + h('핵심 화면 B · 근거를 문서에서 확인')
 + figure('evidence-annotated','화면 2 삽입 위치. 인용·형광펜·주변 문맥과 페이지 이동을 강조할 예정.',placeholder='규정 관리 → 최신 규정 팩 → 중도해지 이자율 → 근거 원문. 형광펜 주변을 잘라 확대하고 페이지 이동·전체 페이지 버튼에 빨간 박스 표시')
 + source('화면 캡처는 별도 삽입 예정. 문서 조회와 실제 추론 결과를 구분하여 촬영. 촬영 조건은 5번과 별도 체크리스트 참조.')),
('3. 사용자 이용 흐름',
 h('접속부터 종료 기록까지')
 + figure('05-userflow','도식 1. 상담원이 근거를 확인하고 설명을 보완하는 사용 흐름.',True)
 + table(['순서','행동','확인 결과'],[
 ('1','배포 URL 접속 후 상담 시작 진입','상담 준비 화면 노출'),
 ('2','상품·최신 팩·필수 안내 확인','이번 상담의 기준 확인'),
 ('3','상담 입력 시작','발화와 항목별 상태가 표시됨'),
 ('4','보완 안내·경보에서 근거 열기','원문 인용 위치 확인'),
 ('5','주변 문맥 확인 후 실제 설명 보완','발화와 조치 기록 추가'),
 ('6','상담 종료 후 리포트 확인','상담 당시 팩과 항목별 결과 확인')],[11,48,41])
 + note('화면의 안내를 읽었다는 사실만으로 설명 완료가 되는 것은 아님. 고객에게 실제로 설명했는지와 사람의 수동 조치를 구분해 확인해야 함.')),
('3. 사용자 이용 흐름',
 h('상담 중 화면을 읽는 순서')
 + figure('consultation-annotated','화면 3. 상담 화면. 대화, 필수 안내 상태, 보완 안내와 근거 위치를 순서대로 확인.',placeholder='실서버에서 예시 음원 재처리 또는 음성 상담 실행. 확정 발화와 경보·근거가 함께 보이는 순간 촬영. 모델 실행 방식과 팩 버전을 함께 기록')
 + table(['영역','읽는 방법','다음 행동'],[
 ('대화','최신 발화 자동 따라가기. 이전 내용을 읽는 동안에는 수동 스크롤 활용','발화자와 전사 내용을 먼저 확인'),
 ('필수 안내','완료 여부와 빠진 요건을 함께 확인','필요한 내용을 실제 상담에서 보완'),
 ('보완 안내·경보','무엇을 다시 확인해야 하는지 파악','연결된 근거 원문 열기'),
 ('근거 원문','강조 구간뿐 아니라 예외·조건이 있는 주변 문맥 확인','필요하면 확대·페이지 이동 후 상담으로 복귀')],[22,45,33])
 + h('상담 후 기록 확인')
 + figure('report-annotated','화면 4. 종료 리포트. 항목별 결과·팩 버전·PDF 저장 위치를 확인.',placeholder='동일 세션을 종료한 뒤 리포트 촬영. 상담 당시 팩 버전과 경보 기록이 보이게 구성. PDF 저장과 재열기까지 별도 확인')
 + note('실서버 배포 후 교체 대상: 모델 실행으로 생성한 발화·경보 화면과 동일 세션의 종료 리포트. 저장된 예시 결과만으로 실시간 추론을 입증하지 않음.',True)),
('4. AI 및 데이터 처리 방식',
 h('전체 아키텍처 · 입력과 판단 기준의 연결')
 + figure('01-system','도식 2. 전체 논리 구성. 홈서버 MVP의 실제 물리 배치는 배포 후 확인 필요.',True)
 + bullets('<b>프론트엔드</b>: 상담 입력·상태·경보·원문을 표시. REST API(요청과 응답 방식)로 목록·문서를 조회하고 WebSocket(지속 연결)으로 상담 이벤트 송수신',
 '<b>서버</b>: 상담 세션, 오디오 전달, 실행 순서, 저장과 화면 전송을 관리',
 '<b>엔진</b>: 서버 프로세스 안에서 팩·확정 발화·상태를 입력받아 판정·경보·조력을 반환',
 '<b>추론 서비스</b>: STT·화자 분리·LLM을 설정된 어댑터로 호출. 외부 서비스와 내부망 모델 배치를 같은 것으로 간주하지 않음',
 '<b>저장</b>: 승인 팩·원문과 상담 이벤트를 보관. 현재 상태와 종료 리포트는 저장된 기록을 해석해 구성')
 + note('서버 배포 대상은 팀원 개인 홈서버임. 기관 내부망·전용 GPU·고가용성 구성을 이미 갖춘 것으로 표시하지 않음.')),
('4. AI 및 데이터 처리 방식',
 h('엔진 아키텍처 · 빠른 판정과 후속 재판정')
 + figure('02-engine','도식 3. 엔진 담당자의 설계를 바탕으로 재구성한 단계별 판정 흐름.',True)
 + table(['단계','입력과 처리','출력·제한'],[
 ('전처리','발화자·신뢰도와 팩 어휘 확인','판단할 범위를 제한하고 원문 보존'),
 ('L1 · 규칙','명시적 요건·표현·값과 단위를 대조','빠른 판정과 수치 불일치 경보'),
 ('L2 · 검색','미해결 항목과 관련 문맥을 검색','후보를 좁힘. 검색 점수만으로 충족 확정 금지'),
 ('L3 · 의미 재판정','필요한 후보와 최근 문맥을 LLM에 전달','허용 항목·상태 변경·결과 형식 검증 후 반영'),
 ('기록·반영','결과의 순서와 앞선 판단과의 관계 기록','실패·시간 초과 시 기존 판단 유지')],[22,40,38])
 + source('설계 근거: 허현준 작성 「말틈 엔진 아키텍처」(2026-09-05). L1·L2·L3는 처리 역할이며 각각 별도의 서버가 아님.')
 + note('기존 실험 구성: Qwen3-8B(역할·의미 판정), multilingual-e5-small(임베딩), Sortformer(화자 분리). STT 공급자는 교체 가능하며 최종 배포 모델·버전은 배포 후 확인 필요.')),
('4. AI 및 데이터 처리 방식',
 h('전사 교정 아키텍처 · 원문을 보존하는 제한적 보완')
 + figure('03-correction','도식 4. 규칙 기반 용어 보완과 선택적인 LLM 보조 교정의 경계.',True)
 + bullets('<b>기본 경로</b>: 팩 용어를 이용해 제한적인 띄어쓰기·용어 해석을 보완하고 판정에 전달',
 '<b>선택적 보조 경로</b>: 현재 발화와 사전에 추린 어절·용어 후보만 LLM에 제공. 임의 문장 재작성은 허용하지 않음',
 '<b>검증</b>: 모델이 선택한 어절과 용어의 조합이 허용 후보에 있는지 다시 확인. 실패·모호함·허용 범위 밖 선택은 현재 해석으로 진행',
 '<b>보존</b>: 저장된 확정 발화와 발화 수치는 유지. 교정은 판정용 해석만 보완하며 상담 기록을 올바른 안내로 덮어쓰지 않음')
 + note('현재 기본 구성은 LLM 보조 교정을 활성화하지 않음. 도식의 점선 경로는 구현된 선택적 연결점이며 상시 실행 기능이나 별도 교정 서버가 아님.')
 + source('설계 근거: 허현준 작성 「말틈 전사 교정 에이전트 아키텍처」(2026-09-05). 교정 단계의 시간까지 포함한 전체 응답 제한을 보장하지 않음.')),
('4. AI 및 데이터 처리 방식',
 h('룰팩 구축 아키텍처 · 기존 문서에서 검증된 기준으로')
 + figure('04-rulepack','도식 5. 오프라인 룰팩 구축과 상담 시 사용하는 발행물의 경계.',True)
 + table(['과정','검사·처리','산출물'],[
 ('원천 고정','공식 출처·문서 일자·해시 확인','추적 가능한 문서 보관본'),
 ('구조·후보 생성','제목·표·문단을 추출하고 규정 후보 구성','항목·요건·쉬운 말·수치 후보'),
 ('근거 대조','인용의 실재·페이지·좌표와 최신성 검사','검증 결과와 검토 후보'),
 ('검수·발행','검토·승인과 컴파일 검증','버전이 고정된 팩'),
 ('런타임 사용','적재한 팩으로 상담 세션의 기준 설정','발화와 항목·근거의 연결')],[22,42,36])
 + note('MVP에는 이미 구축된 팩을 사용함. 새 규정 문서를 웹에서 업로드하면 자동으로 검수·발행·배포되는 사용자 흐름은 제공하지 않음.')
 + source('근거: back/rulepack/docs/PIPELINE.md, SOURCES.md. 로컬 검증용 승인과 개발용 적재 옵션을 금융기관의 실무 승인 체계로 해석하지 않음.')),
('4. AI 및 데이터 처리 방식',
 h('입력과 출력 데이터')
 + table(['구분','핵심 데이터','사용 위치'],[
 ('상담 입력','음성, 발화 텍스트, 화자·시간, 고객 유형','음성 변환·화자 구분·항목 판정'),
 ('기준 입력','팩 버전, 항목 코드, 필수 요건, 금지·위험 예시, 수치 사실','규칙 대조·검색·의미 재판정'),
 ('근거 입력','문서 ID, 페이지, span(인용 구간), bbox(강조 위치 좌표)','원문 표시·형광펜·주변 문맥 탐색'),
 ('판정 출력','항목 상태, 누락 요소, 경보, 근거 참조','상담 화면·종료 리포트'),
 ('사람의 조치','설명 완료·해당 없음의 사유·경보 확인','자동 판단과 구분한 상담 이력')],[20,49,31])
 + h('개인정보와 민감정보의 취급')
 + bullets('시연은 가상 인물 대본·합성 음원과 공개 문서를 사용. 실제 고객 이름·계좌·연락처 등 개인 정보를 입력하지 않는 방식으로 진행',
 '마이크 입력에는 개인 정보가 포함될 수 있으며, 구성에 따라 음성·발화가 외부 STT·LLM 서비스로 전달될 수 있음',
 '외부 전송이 전혀 없거나 익명화·암호화·자동 삭제·권한 분리가 모두 완성된 서비스로 주장하지 않음',
 '상담 기록·음성 보관 여부와 기간은 배포 설정에 따라 확인해야 하며, 기관 도입 시 동의·접근 통제·보존·파기 정책을 별도 정립해야 함')
 + h('근거 해석의 한계')
 + bullets('문서 본문 전체 검색은 기본 서버 조립에 연결되지 않았음. 현재 규정 질의는 팩 항목·연결 근거 범위로 제한됨',
 '문서에 인용이 존재하는지 검사하는 것과 그 인용이 법적 판단을 충분히 뒷받침하는 것은 별개의 검토임',
 '여러 기관의 공개 문서를 활용한 시연용 팩은 특정 은행의 공식 상품 운영 기준이나 승인된 법률 해석을 대신하지 않음',
 '명시적 수치와 복잡한 산식·조건부 계산의 검증 범위를 구분. 대출 승인이나 거래 실행을 수행하지 않음')),
('5. MVP 검증 방법',
 h('접속 준비')
 + note('<b>배포 후 기입</b>: 최종 접속 URL [입력 필요] · 접속 방식 및 심사용 계정 필요 여부 [확인 필요] · 마지막 접속 확인 시각 [입력 필요]',True)
 + bullets('PC의 최신 Chrome 또는 Edge를 기준으로 확인. 마이크 시험은 HTTPS 주소와 브라우저 마이크 권한 허용이 필요',
 '준비물: 스피커 또는 이어폰. 음성 상담 시험 시 마이크 추가 사용. 실제 고객 정보 없이 제공된 예시나 아래 시험 발화 사용',
 '첫 실행에서 규정 팩·문서가 표시되는지 확인한 뒤 추론 기능을 시험. 모델 장애와 문서 조회 장애를 구분')
 + h('A · 모델 실행 없이 확인 가능한 기본 흐름')
 + table(['단계','조작','정상 확인 기준'],[
 ('A1','첫 화면에서 상담 시작 진입','상품 선택과 필수 안내가 표시됨'),
 ('A2','정기예금과 신용대출의 팩 확인','각 상품의 최신 팩만 신규 선택지로 나타남'),
 ('A3','규정 팩에서 근거가 있는 항목 열기','항목 설명과 원문 연결을 확인'),
 ('A4','근거 원문 열기 후 확대·페이지 이동','강조 위치와 주변 문맥을 확인하고 복귀 가능'),
 ('A5','상담 이력의 저장 기록 재생','기존 발화·판정이 순서대로 표시됨'),
 ('A6','종료 리포트에서 PDF 저장','파일을 다시 열어 팩 버전·항목별 기록 확인')],[10,45,45])
 + note('A5·A6은 배포 서버에 예시 상담 기록이 준비되어 있어야 함. 저장된 기록의 재생 성공은 STT나 LLM이 새로 실행됐다는 증거가 아님.')
 + source('실행과 별개로 URL 접근 기간 유지 필요: '+RULES+'.')),
('5. MVP 검증 방법',
 h('B · 음성·판정 연결을 확인하는 시험')
 + table(['시험','입력·조작','기대 결과'],[
 ('예시 음원','상담 이력의 시연 메뉴에서 정기예금 중도해지 예시를 새로 실행','음원을 다시 처리하며 발화·경보·근거가 생성됨. 저장 기록 재생과 모드 구분'),
 ('숫자 오류','DEP-2026.08-v6 · 텍스트 입력 · 직원 발화: “이자소득세는 14퍼센트입니다.”','DEP-TAX-001에서 발화 14%와 기준 15.4%의 수치 오류 경보 및 원문 근거 확인'),
 ('금지 취지','LOAN-2026.08-v7 · 직원 발화: “대출 승인은 무조건 확정입니다.”','L2·L3 연결 시 LOAN-BAN-001의 금지 판정·경보 확인. 후보만 표시되면 최종 판정 성공으로 세지 않음'),
 ('규정 질문','신용대출 팩에서 “대출에 필요한 서류는 무엇인가요?” 질문','임베딩 연결 후 팩에서 근거를 찾으면 승인 안내와 출처 표시'),
 ('근거 없음','“오늘 점심 메뉴를 추천해 주세요.” 질문','규정 근거를 찾지 못했다는 안내. 임의 금융 답변 생성 금지'),
 ('수동 조치','해당 없음 처리에서 사유 입력 후 리포트 확인','사유와 사람이 한 조치가 기록에 남음')],[19,45,36])
 + source('시험 발화는 입력 예시이며 모든 음향·모델 조건에서 같은 출력이 보장되는 고정 정답은 아님. 인식 텍스트와 팩 기준을 함께 확인해야 함.')
 + figure('live-verification-annotated','교체 화면 S1. 실서버에서 음성 또는 예시 음원 입력 후 새로 생성된 발화·수치 경보·근거.',placeholder='배포 후 정기예금 세율 오류 장면을 실제 추론으로 생성. ① 발화 ② 오류값과 기준값 ③ 원문 근거를 빨간 박스로 표시. 동일 세션 ID·모드·팩 버전과 시간을 촬영 기록에 남김')
 + note('실서버 배포 후 확인 필요: STT·화자 역할·LLM 연결, 처음 실행과 반복 실행의 지연, 동일 상담 종료 리포트까지의 연결.',True)),
('5. MVP 검증 방법',
 h('실패 상황과 복구 확인')
 + table(['증상','확인·조치','통과 기준'],[
 ('마이크 입력 불가','HTTPS·마이크 권한·입력 장치 확인 후 재시도','권한 문제를 안내하고 입력 경로 복구 가능'),
 ('서버 연결 끊김','연결 안내 확인 후 다시 연결 또는 이력 확인','저장된 상담을 식별하고 중복·누락 여부 확인'),
 ('근거 이미지 불러오기 실패','다시 시도 후 페이지·출처 연결 확인','이전 항목의 근거가 현재 항목처럼 남지 않음'),
 ('LLM 응답 지연·실패','첫 판정과 후속 판정을 구분해 확인','실패를 설명 완료나 위반 확정으로 바꾸지 않음'),
 ('리포트 내용 불일치','상담 세션·팩 버전·종료 여부 확인','해당 상담의 기록과 저장 PDF가 일치')],[25,40,35])
 + h('MVP와 실운영 환경의 차이')
 + table(['영역','대회 MVP','실운영 전 필요한 보강'],[
 ('물리 배포','팀원 개인 홈서버 URL 배포 대상. 현재 미배포','기관 내부망·추론 자원·망 구간 설계와 실배치 검증'),
 ('추론','설정한 STT·LLM 서비스에 의존','음향 조건·동시 상담 부하·장애 복구 검증'),
 ('규정 갱신','기존 문서로 만든 사전 구축 팩 사용','개정 감지·후보 검토·승인·배포 절차 연결'),
 ('접근과 보존','시연 데이터 중심. 운영 보안 완성 주장 안 함','기관 인증·권한·감사·동의·보존·삭제 체계'),
 ('업무 범위','설명 지원·기록. 실제 거래·심사 실행 없음','업무 시스템 연계와 책임·검토 절차 확정')],[20,39,41])
 + note('교체 화면 S2: 배포 서버의 실제 종료 리포트와 저장 PDF. S1과 동일 세션을 사용하고, 이 문서의 URL·접속 방식·미배포 표기도 함께 갱신해야 함.',True)
 + source('제출 전 점검: 모든 “배포 후 기입·확인·교체” 표시 검토, 계정·URL 확인, 새 브라우저 접속 시험, 접근 유지 기간 점검. 별도 「내일 교체 체크리스트」 참조.')),
]

CSS = '''
@page{size:A4;margin:0}*{box-sizing:border-box}body{margin:0;background:#e5e8e9;color:#111;font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:10.5pt;line-height:1.65}.page{width:210mm;min-height:297mm;margin:8mm auto;background:white;padding:17mm 18mm 17mm;position:relative;break-after:page}.page:last-child{break-after:auto}.running{font-size:8pt;letter-spacing:.04em;color:#555;margin-bottom:7mm}.running span{float:right}.section{background:#ededed;border:1px solid #b8b8b8;padding:3mm 4mm;margin:0 0 5mm;font-size:15pt;line-height:1.3;font-weight:700}h1,h2,h3{color:#000}h1{font-size:43pt;line-height:1.1;margin:4mm 0}h2{font-size:15pt;background:#ededed;border:1px solid #b8b8b8;padding:3mm 4mm;margin:7mm 0 4mm}h3{font-size:12pt;margin:4mm 0 2mm}p{margin:2mm 0}ul{padding-left:5mm;margin:2mm 0 4mm}li{margin:1.6mm 0;word-break:keep-all;overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;table-layout:fixed;margin:3mm 0 4mm;font-size:9.4pt;line-height:1.55}th,td{border:1px solid #c9cfd1;padding:2.2mm 2.5mm;vertical-align:middle;word-break:keep-all;overflow-wrap:anywhere}th{background:#e9eeee;font-weight:700;text-align:left}tbody tr:nth-child(even){background:#f8fafa}td:first-child{font-weight:600}.hero{padding:5mm 0}.eyebrow{font-size:10pt;color:#36515a;font-weight:700}.lead{font-size:18pt;line-height:1.5;font-weight:700}.lead.small{font-size:16pt;margin:4mm 0 5mm}.note,.pending{padding:3mm 4mm;margin:4mm 0;background:#f2f7f7;border-left:3px solid #267d93;font-size:9.5pt;line-height:1.55}.pending{background:#fff7ec;border-color:#b46b1d}.source{font-size:8pt;line-height:1.5;color:#555;margin:3mm 0}.source a{color:inherit;text-decoration:underline}.screen,.diagram{margin:3mm 0 4mm;break-inside:avoid}.screen img,.diagram img{width:100%;height:auto;display:block;object-fit:contain}.screen img{max-height:68mm}.diagram img{max-height:112mm}figcaption{font-size:8.5pt;color:#444;margin:2mm 0;line-height:1.5}.placeholder{border:2px dashed #b46b1d;background:#fff9f0;padding:6mm;min-height:40mm;display:flex;justify-content:center;flex-direction:column;gap:2mm;color:#694616}.placeholder small{font-size:8pt}.footer{position:absolute;bottom:8mm;left:18mm;right:18mm;text-align:center;color:#666;font-size:8pt}.toolbar{position:sticky;top:0;z-index:1000;background:#18333d;color:white;padding:12px 20px;display:flex;gap:12px;align-items:center;font-size:13px}.toolbar button{padding:8px 12px;cursor:pointer;border:0;border-radius:4px;font-weight:600}.editing [contenteditable=true]{outline:1px dashed #76a9b3}.editing figure{cursor:pointer}.toolbar small{max-width:650px;line-height:1.4}.meta{font-size:9pt;color:#333;margin:0 0 5mm}.figure-status{font-size:8pt;color:#78501e}.print-note{display:none}@media print{body{background:white}.page{margin:0;box-shadow:none}.toolbar{display:none!important}[contenteditable=true]{outline:0!important}.print-note{display:block}}@media screen and (max-width:850px){.page{margin:0;max-width:100%;padding:6vw}.toolbar{flex-wrap:wrap}.footer{position:static;margin-top:8mm}}
'''

JS = '''
let editing=false;
function toggleEdit(){editing=!editing;document.body.classList.toggle('editing',editing);document.querySelectorAll('.editable').forEach(x=>x.contentEditable=editing);document.getElementById('edit').textContent=editing?'편집 종료':'문구 편집';}
function saveHtml(){const c=document.documentElement.cloneNode(true);c.querySelector('body').classList.remove('editing');c.querySelectorAll('.editable').forEach(x=>x.contentEditable='false');c.querySelector('#edit').textContent='문구 편집';const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['<!doctype html>'+c.outerHTML],{type:'text/html;charset=utf-8'}));a.download=document.title+'.html';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
document.querySelectorAll('figure').forEach(fig=>fig.addEventListener('click',()=>{if(!editing)return;const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';input.onchange=()=>{const f=input.files[0];if(!f)return;const reader=new FileReader();reader.onload=()=>{let img=fig.querySelector('img');if(!img){img=document.createElement('img');img.alt=fig.querySelector('figcaption').textContent;fig.prepend(img);}img.src=reader.result;fig.querySelector('.placeholder')?.remove();};reader.readAsDataURL(f);};input.click();}));
'''

def build(name, number, pages):
    out=[]
    for i,(title,body) in enumerate(pages,1):
        meta = table(['팀명','구성원 성명'],[('말해모해','임한빈(팀장), 노순혁, 서재오, 허현준')],[25,75]) if i==1 else ''
        out.append(f'<section class="page" data-page="{i}"><div class="running">첨부 {number}　2026 금융 AI Challenge {name}<span>말해모해 · 말틈</span></div>{meta}<main class="editable" contenteditable="false"><h2 class="section">{title}</h2>{body}</main><div class="footer">{i} / {len(pages)}</div></section>')
    title=f'말해모해_말틈_{name}'
    full=f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}</style></head><body><div class="toolbar"><b>{name} 편집 원본</b><button id="edit" onclick="toggleEdit()">문구 편집</button><button onclick="saveHtml()">수정본 HTML 저장</button><button onclick="window.print()">PDF로 인쇄</button><small>편집 모드에서 본문을 수정하거나 그림을 클릭해 교체 가능. 저장 후 새 파일을 열어 확인. PDF 출력은 A4·배율 100%·머리글/바닥글 해제·배경 그래픽 켜기.</small></div>'+''.join(out)+f'<script>{JS}</script></body></html>'
    if chr(0x2014) in full:
        raise ValueError('Prohibited punctuation')
    (ROOT/f'{title}.html').write_text(full,encoding='utf-8')
    (ROOT/f'{title}_본문.md').write_text('\n\n'.join(f'## {t}\n\n'+re.sub('<[^>]+>',' ',b) for t,b in pages),encoding='utf-8')
    return title

if __name__=='__main__':
    for args in [('기획서',1,PROPOSAL),('기능명세서',2,SPEC)]:
        print(build(*args))
