# 원천 감사와 교체

규정 PDF 7종의 현행성 판정과 교체 절차. 기준일 2026-08-29.

이 문서는 법률 자문이나 은행 내부 규정이 아니라 **발행 차단 판단의 기록**이다.

## 원천별 판정

| 원천 | 확인 결과 | 상태 |
| --- | --- | --- |
| 금융소비자보호법 제21조 | 현행 법령에서 단정적 판단 금지 span 유지 | `confirmed` |
| 금융소비자보호법 제20조 | 제3자 이익을 위한 특정 상환방식 강요 span 확인 | `confirmed` |
| 예금거래기본약관 | 씨티은행 공식 게시본과 SHA-256 · 9쪽 일치 | `confirmed` |
| 은행여신거래기본약관 | 우리은행 공식 게시본과 SHA-256 · 9쪽 일치 | `confirmed` (현재 후보가 안 씀) |
| 정기예금 상품설명서 | 공식 후보도 2026-03-27 심의 만료 · 보호한도 5천만원 표기 | `unverified` · `conflict` |
| 가계대출 상품설명서 | 2026-08-29 에 2025.01 개정본(24쪽)으로 교체 완료 | `confirmed` |

후보 19건 기준 `confirmed` 13 · `unverified` 5 · `conflict` 1. 부정 표본 2건은 집계에서 제외한다.

## 교체가 필요한 것

정기예금 상품설명서 하나가 남았다. 공식 후보 파일조차 심의 유효기간이 지나 교체본으로 쓸 수 없으므로, **신한은행에서 심의 유효기간 내 현행 설명서를 새로 확보**해야 한다. 이것이 풀리면 예금 6건이 함께 풀린다.

## 교체 절차

1. 원천 담당자가 공식 URL 과 문서 시행 또는 심의 유효기간을 확인한다
2. 승인된 PDF 로 `assets/03_규정문서/` 의 대응 파일을 교체한다
3. `MANIFEST.md` 의 문서 링크 · 규모를 갱신한다
4. `python -m rulepack.cli build` 를 돌린다. page · span · bbox 가 바뀐 후보는 자동 통과시키지 않고 재검토한다
5. `config/source_audit.json` 의 후보별 `source_sha256` 과 판정을 새 원천 기준으로 갱신한다
6. 감사 기록을 새 날짜 파일로 남긴다(`artifacts/source_refresh_<YYYYMMDD>.json`). 기존 파일은 그날 판단의 근거라 고치지 않는다
7. `verify --strict` · 전체 테스트 · `contracts/validate.py` 를 통과시킨다
8. 업무 승인자가 RC(Release Candidate: 발행 전 검토 후보)를 검토하고 서명 승인한다

## 2026-08-29 교체 기록

가계대출 설명서를 하나은행 2025.01 개정본으로 교체했다.

- 받은 파일의 SHA-256 이 8/26 에 기록해둔 후보 해시(`02f2d0ef...f2cb1`)와 일치
- 26쪽에서 24쪽으로 줄었으나 **근거 span 9건의 page 가 하나도 안 바뀜**. 앞부분 구성이 같았고 좌표는 `find_span` 이 새로 뜸
- `source_audit.json` 의 06 기반 8건을 새 해시로 올려 `source_replacement_required` 해제
- 감사 갱신을 빠뜨리면 `source_audit_hash_mismatch` 로 다시 막힌다. `test_replaced_product_document_clears_publication_blockers` 가 이를 잡는다

## 발행 경계

- 이 파이프라인의 정상 종점은 RC 와 리뷰 큐다. 운영 팩을 자동 발행하지 않는다
- `confirmed` 만으로 발행되지 않는다. 근거 검증 · 서명 승인 · RC digest 검증을 모두 통과해야 한다
- 감사 레코드는 로컬 원천 PDF 의 SHA-256 과 묶인다. 해시가 어긋나면 `source_audit_hash_mismatch` 로 차단된다
