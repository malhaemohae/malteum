# rulepack 현황

기준일: 2026-08-29. `python -m rulepack.cli build` 결과와 `config/source_audit.json` 에서 뽑은 값이다.

## 후보 판정

| 상품 | 발행 가능 | 검토 대기 | 발행 차단 | 자동 폐기 |
| --- | ---: | ---: | ---: | ---: |
| 예금 신규 | 3 | 1 | 6 | 1 |
| 신용대출 | 8 | 2 | 0 | 1 |

- 발행 가능 11건: `DEP-DOC-001` · `DEP-BAN-001` · `DEP-RSK-001` · `LOAN-INT-001` · `LOAN-ARR-001` · `LOAN-PRE-001` · `LOAN-DSR-001` · `LOAN-WDR-001` · `LOAN-CIC-001` · `LOAN-BAN-001` · `LOAN-RSK-001`
- 실제 발행에는 사람 승인과 HMAC 서명이 따로 필요하다. `confirmed` 만으로 나가지 않는다.
- 자동 폐기 2건(`DEP-REJ-001` · `LOAN-REJ-001`)은 부정 표본이다. 원문 미존재와 page 불일치를 파이프라인이 잡는지 보는 장치라 통과하면 안 된다.

## 남은 막힘

### 예금 6건 · 원천 교체 대상이 없음

정기예금 상품설명서(`05_`)가 구판인데 **공식 후보 자체가 2026-03-27 심의 만료**이고 예금자보호한도를 5천만원으로 적고 있다. 교체본으로 쓸 수 없어 신한은행에서 현행 설명서를 새로 확보해야 한다.

`DEP-PRO-001` 은 여기에 더해 2025-09-01 시행 1억원 한도와 정면 충돌해 `stale_source` 로 따로 막혀 있다.

### 검토 대기 2건 · 근거의 의미 범위 부족

`LOAN-RDR-001`(금리인하요구권)과 `LOAN-DOC-001`(자필 기재 문구)은 exact span 은 원문에 실재하지만, 그 문구만으로 요구 요건 전체나 필요 서류를 입증하지 못한다. `evidence_scope_mismatch` 로 사람 검토를 기다린다. `docs/CONTRACT_GAPS.md` 참조.

## 최근 변경

- 2026-08-29 가계대출 설명서를 2025.01 개정본(24쪽)으로 교체. 대출 차단 8건 해제
- 2026-08-29 위험 신호 2건을 `risk` type 으로 발행. 계약 v0.4 가 이미 채운 공백을 코드가 뒤늦게 따라감
- 2026-08-29 `pack` · `pack_item` · `item_embedding` 테이블 추가

## 되짚는 법

```bash
cd back
uv run python -m rulepack.cli build            # 후보 생성. artifacts/review_*.json
uv run python -m rulepack.cli verify --strict  # 결정성·고정 의존성·java·계약 검증
```

JDK 21 과 `uv` 가 필요하다. 산출물은 `.gitignore` 로 추적하지 않는다. 같은 원천·코드·파서 버전이면 같은 값이 나오므로 레포에 둘 이유가 없다.
