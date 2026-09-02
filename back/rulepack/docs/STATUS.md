# rulepack 현황

기준일: 2026-08-30. `python -m rulepack.cli build` 결과와 `config/source_audit.json` 에서 뽑은 값이다.

## 후보 판정

| 상품 | 발행 가능 | 검토 대기 | 발행 차단 | 자동 폐기 |
| --- | ---: | ---: | ---: | ---: |
| 예금 신규 | 9 | 0 | 0 | 1 |
| 신용대출 | 9 | 2 | 0 | 1 |

- 발행 가능 18건: `DEP-INT-001` · `DEP-INT-002` · `DEP-INT-003` · `DEP-PRO-001` · `DEP-TAX-001` · `DEP-LIM-001` · `DEP-DOC-001` · `DEP-BAN-001` · `DEP-RSK-001` · `LOAN-INT-001` · `LOAN-ARR-001` · `LOAN-ARR-002` · `LOAN-PRE-001` · `LOAN-DSR-001` · `LOAN-WDR-001` · `LOAN-CIC-001` · `LOAN-BAN-001` · `LOAN-RSK-001`
- 실제 발행에는 사람 승인과 HMAC 서명이 따로 필요하다. `confirmed` 만으로 나가지 않는다.
- 자동 폐기 2건(`DEP-REJ-001` · `LOAN-REJ-001`)은 부정 표본이다. 원문 미존재와 page 불일치를 파이프라인이 잡는지 보는 장치라 통과하면 안 된다.

## 남은 막힘

### 검토 대기 2건 · 근거의 의미 범위 부족

`LOAN-RDR-001`(금리인하요구권)과 `LOAN-DOC-001`(자필 기재 문구)은 exact span 은 원문에 실재하지만, 그 문구만으로 요구 요건 전체나 필요 서류를 입증하지 못한다. `evidence_scope_mismatch` 로 사람 검토를 기다린다. `docs/CONTRACT_GAPS.md` 참조.

## 최근 변경

- 2026-08-29 가계대출 설명서를 2025.01 개정본(24쪽)으로 교체. 대출 차단 8건 해제
- 2026-08-29 위험 신호 2건을 `risk` type 으로 발행. 계약 v0.4 가 이미 채운 공백을 코드가 뒤늦게 따라감
- 2026-08-29 `risk` 항목에 `risk_examples` 부여. 계약이 요구하는데 빠져 있어 운영 컴파일이 막혔음
- 2026-08-29 `pack` · `pack_item` · `item_embedding` 테이블 추가
- 2026-08-29 임베딩 어댑터와 `scripts/load_pack.py` 추가. 팩이 실제로 벡터를 만든 구현을 기록하게 됨
- 2026-08-30 임베딩 모델을 `intfloat/multilingual-e5-small` 로 확정. CPU 중앙값 7.0ms 로 L2 지연 예산 통과
- 2026-08-30 `LOAN-RSK-001` 을 `risk` → `forbidden` 으로 정정. 근거 조문이 은행원을 구속하는데 고객 발화로 분류돼 있었음
- 2026-08-30 `DEP-RSK-001` 근거 조문을 예금거래기본약관 제4조 → 제6조로 정정
- 2026-08-30 발행 기관을 MANIFEST 표에서 읽게 바꿈. 표준약관 2건의 오표기(게시 은행 → 은행연합회) 정정
- 2026-08-30 `publish` 를 처음 실행. 예금·대출 팩 둘 다 발행하고 M2 로더가 읽는 것까지 확인
- 2026-08-30 상품 목록·검증 항목 하드코딩을 `products.json`·번들에서 뽑도록 정리
- 2026-08-30 정기예금 설명서를 심의 유효기간 내 현행본으로 교체. 예금 6건 차단 해제로 발행 가능 11 → 17건. 옛 원천은 심의 만료에 보호한도 5천만원 표기였고, 새 원천은 2025-09-01 시행 1억원 반영본
- 2026-08-30 팩 저장을 M1 의 `rule_packs`·`pack_embeddings` 로 통합. 따로 만들었던 `pack`·`pack_item`·`item_embedding` 은 timestamptz 왕복에서 `published_at` 표기가 바뀌어 `pack_sha256` 대조가 깨졌음. M2 도 `SELECT doc` 한 줄로 팩을 그대로 받게 됨
- 2026-08-30 적재를 생 SQL 에서 M1 의 ORM 모델로 바꿈. 열을 두 곳에 적으면 계약이 늘 때 스크립트가 조용히 뒤처짐. `RulePack.embeddings` 관계도 함께 넣어 삽입 순서와 삭제를 모델이 맡음
- 2026-08-30 M1 의 `scripts/seed_pack.py` 를 `load_pack.py` 에 흡수. 같은 테이블에 두 방식으로 넣으면 어느 쪽으로 넣었느냐에 따라 `pack_embeddings` 가 비어 L2 검색이 조용히 안 됨. 그쪽의 계약 스키마 검증과 여러 팩 한 번에 넣기를 가져옴
- 2026-08-30 적재도 발행과 같은 무결성 검사를 거치게 함. 서명 없는 팩 본문은 `--unsigned` 없이는 거절
- 2026-08-30 계약 fixture 4종을 새 예금 원천 기준으로 재발행. 팩 · 이벤트 · 판정 케이스 · WS 메시지가 모두 옛 원천 문구를 담고 있었음. 항목 코드 3건이 바뀌어 M2 테스트 기대값도 함께 갱신
- 2026-09-01 `DEP-BAN-001` 의 forbidden_examples 를 1문장에서 5문장으로 보강. 엔진 팀 L2 실측에서 "만기 지나도 금리 그대로" 발화의 검색 후보에 이 항목이 못 들었음. 만기 후 금리·중도해지 단정 표현을 추가. 다음 팩 발행부터 반영됨
- 2026-09-01 L2 골든셋(`config/golden_utterances.json`)과 평가 스크립트(`scripts/eval_l2_goldenset.py`) 추가. 검색 방식(모델 교체·자모 BM25·융합)을 바꿀 때마다 top-1 · recall@k · 무관 발화 분리를 같은 기준으로 잰다
- 2026-09-02 `DEP-BAN-001` 보강분(금지 예시 1 → 5문장)을 계약 fixture 팩에 반영. 엔진·서버가 읽는 팩이 fixture 라 여기 반영돼야 L2 검색면에 실림. 재빌드 산출물과 canonical 대조로 fixture 에 다른 드리프트가 없음을 확인했고, 이 대조를 `tests/rulepack/test_fixture_matches_canonical.py` 가 상시 수행. 유일한 차이는 `DEP-INT-002` 의 옛 numeric_facts 로, 시연 숫자 대조 경로를 살리려는 의도된 임시 부채(`contracts/fixtures/README.md` 참조). 주의: `pack_version` 을 v4 로 유지한 제자리 수정이라, v4 를 이미 적재한 DB 는 `load_pack --replace` 로 다시 넣어야 새 검색면이 실리고, `pack_version` 을 키로 쓰는 L3 판정 캐시·녹화 테이프도 무효화가 필요함
- 2026-09-02 L2 골든셋 baseline 실측 기록. 예금 recall@3 8/10 · 대출 7/8, 관련·무관 top1 간격 0.02 안팎. 수치와 조건은 `docs/PIPELINE.md` 의 baseline 표 참조
- 2026-09-02 대출 후보 9건에 `l1_patterns` 부여(`LOAN-INT`·`RDR`·`ARR`·`PRE`·`DSR`·`WDR`·`CIC`·`BAN`·`RSK`). 시연 대본을 엔진에 통과시켜 보니 대출 팩은 `DSR`·`RSK` 둘만 패턴이 있어 나머지가 엔진의 임시 키워드(`[DUMMY]`)에 의존했고, 은행원이 요건 요소 이름을 글자 그대로 말해야만 L1 이 잡혔음. 요소마다 정규식을 넣고 `tests/rulepack/test_l1_patterns.py` 가 판정 대상 항목의 요소 커버리지·대표 문장 적중·정정 문장 비적중을 상시 검사. 발행된 `LOAN-2026.08-v2` 에는 없고 다음 발행부터 실림
- 2026-09-02 대출 팩에 숫자 사실 2건 추가. `LOAN-PRE-001` 중도상환해약금 부과 기간 3년, 새 항목 `LOAN-ARR-002`(연체가산이자율 수치) 연 3%. 대출 팩에는 `numeric_facts` 가 하나도 없어 ⑤ 숫자 오류 감지가 통째로 비어 있었음. 파이프라인이 숫자 사실의 근거를 항목 근거 span 으로 고정하므로(`pipeline.py`), 3% 가 적힌 줄이 연체이자율 산식 줄과 다른 chunk 라 `LOAN-ARR-001` 에 붙일 수 없어 항목을 하나 더 냄. 청약철회 14일은 같은 이유로 못 실음(항목 근거는 의사표시·반환 문장이고 14일 문장은 다른 chunk)
- 2026-09-02 `LOAN-BAN-001` 금지 예시 1 → 5문장. `DEP-BAN-001` 과 같은 이유로, 시연 대본의 "확정이라고 보시면 돼요" 류가 L2 예시 검색면에 없었음. `LOAN-CIC-001` 의 '동의' 패턴을 정보·범위와 붙은 꼴로 좁힘. 한 단어면 "동의서에 서명해 주세요" 같은 절차 안내까지 요소를 채웠음
- 2026-09-02 `LOAN-2026.08-v3` 발행(위 변경 전부 반영, 항목 9개). 예금 v4 와 같은 방식으로 계약 fixture(`contracts/fixtures/rulepack_LOAN-2026.08-v3.json`)에 실음. 서버의 `pack_dir` 이 fixtures 폴더라 여기 있어야 시연 서버가 대출 세션을 열 수 있음. `tests/rulepack/test_fixture_matches_canonical.py` 가 예금과 같이 상시 대조. 승인 서명은 로컬 검증 키로 했고 `published_by` 는 예금 fixture 와 같은 `contract-fixture`

## 되짚는 법

```bash
cd back
uv run python -m rulepack.cli build            # 후보 생성. artifacts/review_*.json
uv run python -m rulepack.cli verify --strict  # 결정성·고정 의존성·java·계약 검증
```

JDK 17 이상(CI 는 21)과 `uv` 가 필요하다. 산출물은 `.gitignore` 로 추적하지 않는다. 같은 원천·코드·파서 버전이면 같은 값이 나오므로 레포에 둘 이유가 없다.
