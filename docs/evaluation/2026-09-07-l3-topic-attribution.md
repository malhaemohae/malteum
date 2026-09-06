# L3 의미 귀속 수정 검증 기록 (2026-09-07)

PR: [L3 의미 귀속 — 주제를 먼저 귀속시켜 다른 항목의 설명을 인정하지 않게](https://github.com/malhaemohae/malteum/pull/51) (`feat/engine-grounded-l3`, `dev` 대상). 증거 파일은 [같은 이름의 폴더](2026-09-07-l3-topic-attribution/)에 있다. 비밀정보는 제거했다.

## 문제

전사가 정확한 연체금리 문장 `연체하시면 대출이자율에 연체가산이자율 연 3%가 더해진 연체이자율이 적용됩니다.` 를 넣어도 Qwen3-8B 가 기한이익상실(LOAN-EXP-001)을 `partial`(누락: 기한이익상실 사유)로 갱신했다. L2 유사도로 후보에 오른 항목을 L3 가 의미적으로 구분하지 못한 경로다. 이전 기록은 [엔진 회귀 검증 기록](2026-09-07-engine-regressions.md)에 있다.

## 고정 조건

- LLM: OpenRouter `qwen/qwen3-8b`, temperature 0, reasoning off, 캐시 없음. 교정·답변 생성 모델은 쓰지 않았다.
- 고정 회귀: 개발 6문장 + 별도 12문장(`scope_holdout.json`, SHA-256 `fb5ff4e2ff91b8ef10e0405b0d76d09bb5079fdba48424457d01b77f1e718a58`, 변경 없음).
- 미사용 검증셋: `scope_holdout2.json` 17문장(SHA-256 `6c8263a17ed930a1eeed8e08221a413e4d98452f5071e8ca1e15cf1149f1e7c8`). 수정 설계를 고정한 뒤 처음 실행했고, 결과를 본 뒤 기대값을 바꾸지 않았다. 이제부터는 회귀셋이다.
- 음성 E2E: A 시나리오 1회, 로컬 Qwen3-ASR-1.7B(GPU)·Sortformer(CPU)·multilingual-e5-small(CPU), 새 앱·빈 캐시, `back/scripts/evaluate_current.py` + `score_current.py`.

## 원인과 수정

1. 산문 규칙은 무력했다. 시스템 프롬프트에 '주제 귀속 → 요소 충족' 순서를 아무리 적어도 출력이 바뀌지 않았다(선별 8/18, 기준선과 동일).
2. 툴 인자 구조를 바꾸자 걸러졌다. 모델이 자유 문장으로 적은 주제("연체 시 연체가산이자율 적용")는 처음부터 정확했고, 그 주제와 항목 이름의 관계를 적을 자리와 '후보가 아닌 다른 항목 이름'이 필요했다.

최종 설계(`engine/tiers/l3/tools.py`, `PROMPT_VERSION=2026-09-07.topic-relations.v4`):

- 툴 인자 순서 = 판정 순서: `utterance_topic`(주제 한 구절, 항목·요소 이름을 베끼지 않음) → `topic_relations`(required 후보마다 explains_item / other_topic / unrelated) → `verdicts`(`stated_elements`: 실제로 말한 요소만). required/omission 의 상태·누락은 stated_elements 로 계산하고, explains_item 이 아닌 required 후보의 verdict 는 버린다. forbidden 은 주제가 아니라 취지의 문제라 관계로 거르지 않는다. axis 는 항목 타입·화자에서 정한다.
- `JudgePrompt.other_item_names`(계약 필드, 기본값 `()`): 후보가 아닌 팩 항목 이름. **계약 변경이므로 전원 합의가 필요하다.** 서버는 JudgePrompt 를 쓰지 않는다.
- 본문에서 판정 대상 utterance 를 마지막에 둔다.
- 파서 누적: 현재 partial 인 항목은 이전에 채운 요소를 다시 요구하지 않는다(L1 `known` 과 같은 규칙). 빠진 요소 없는 partial 은 거부.
- 검증 스키마만 관대하게: 모델이 지어낸 요소 이름·금지 항목 관계 값은 형식 오류가 아니라 '말하지 않음'으로 무시한다. 형식 오류 재시도는 3초 예산을 넘겼다.
- `PROMPT_VERSION` 을 cache_key 에 넣어 옛 정책의 캐시 응답을 재사용하지 않는다.

특정 문장·정답·시나리오에 의존하는 분기는 없다. 팩의 항목 이름과 요소 목록만 쓴다.

## 선별 실험 (각 18문장 1회, 하네스 `screening/scope_harness.py`)

| 변형 | 통과 | 비고 |
| --- | ---: | --- |
| 기준선(산문 규칙만 수정) | 8/18 | 수정 전과 동일 |
| topic | 9/18 | 주제 문장만 추가 |
| topic+stated | 11/18 | 말한 요소 표기 |
| topic+stated+noplain | 13/18 | 쉬운 말 제거. 의역 미탐 증가 |
| topic+stated+relation | 11/18 | verdict 안의 3지선다 |
| topic+rel2+stated | 13/18 | verdict 앞의 관계 배열 |
| topic+rel2+stated+catalog | 15/18 | 후보 밖 항목 이름 |
| topic+rel2+stated+catalog+uttlast | 16/18 | 발화를 본문 끝에. **채택** |
| stated / hints / both | 0~6/18 | 초기 실행. 동시 18요청으로 속도 제한 오류 7~8건 포함 |

주제 설명을 "짧게"로 줄인 절감 시도는 모델이 요소 이름을 베껴 주제로 적어 27/54 로 무너졌다. 검증된 문구를 유지했다.

## 최종 결과 (v4)

| 검사 | 수정 전 | 수정 후 |
| --- | ---: | ---: |
| 고정 회귀 개발 6문장 × 3회 | 9/18 | 15/18 |
| 고정 회귀 별도 12문장 × 3회 | 15/36 | 30/36 |
| 미사용 검증셋 17문장 × 3회 | — | 51/51 |
| 기존 실제 LLM 검사 `test_live_llm.py` | — | 4/4 |
| 통합 경로(실물 e5 후보 선택 → refine → L3 → 캐시) | — | 1/1 |
| 형식 오류·호출 실패 | — | 0 |

- 오탐(다른 주제를 인정)은 105회 중 0건이다.
- 남은 실패 9건: 기한이익상실 의역("빌린 돈을 한 번에 모두 돌려주셔야", "남은 대출금을 만기 전에 전부 갚으셔야")에서 불이익 요소를 인정하지 않은 미탐 6건(partial 로 남음, P3 방향), 두 주제 복합 문장에서 사유를 과잉 인정해 met 로 올린 3건(mixed-topics). 세 번째 실패는 요소 과잉 인정이며 이전 v2 실행에서는 3회 모두 통과했던 사례라 실행 간 편차가 있다.
- 집중 검사 지연(동시 3프로세스): p50 1.98초, p95 3.33초, 최대 3.57초. 수정 전 1.2~1.8초. 후보 2개 프롬프트가 가장 느리다.

## A 음성 E2E

| 항목 | 수정 직후(v1) | 최종(v4) |
| --- | --- | --- |
| 요약 일치 | 위반 1 기대 / 0 실제 | 일치 |
| 항목 상태 | 8/8 | 8/8 |
| 경보 TP/FP/FN | 3/0/0 | 3/0/0 |
| 위반 TP/FP/FN | 0/0/1 | 1/0/0 |
| 화자 · 원본 발화 포함 | 27/27 · 16/16 | 27/27 · 16/16 |
| L3 7회 지연 | p50 2.88초, 예산 초과 2회 | p50 1.94초, p95 2.54초, 예산 초과 0회 |
| 형식 오류 | 1 | 0 |
| PDF | 200, 8,565 bytes, 헤더 정상 | 200, 8,565 bytes, 헤더 정상 |

v1 은 프롬프트가 2,030 토큰으로 늘어 예산 초과가 잦았다. 모델에게 보내는 문구는 그대로 두고 쓰지 않는 필드를 없애고 검증만 관대하게 한 v4 에서 7/7 예산 안이었다. 단 이전 숫자 수정 E2E 에서도 7회 중 1회 초과가 있었듯 OpenRouter 지연 편차가 커서, 이 1회 결과를 3초 예산 상시 통과로 해석하지 않는다.

## 하지 않은 것

- C(LIVE 전사 오류)는 서버 담당이 flush 임계값을 조정 중이며 이 작업에 포함하지 않았다. 원본 LIVE 음성 재현은 미검증이다.
- B~D 전체 음성 QA, 프런트 QA 는 하지 않았다.
- 계약 필드 추가와 `judge_cases.json` 정정(#49)은 담당자 합의가 필요하다.

## 주의

- pytest 의 긴 traceback 이 LiteLLM 요청 인자(`api_key`, `Authorization` 헤더)를 그대로 찍는다. 실물 호출 테스트 로그를 공유하기 전에 확인하거나 `--tb=short` 로 실행한다. 이 폴더의 로그는 검사했다.
- 이번에 시작한 평가 컨테이너 `malteum-eval-asr-0906`, `malteum-eval-diar-0906` 은 종료 후 정지했다.

## 재현

```sh
cd back
MALTEUM_LIVE_REGRESSION=1 uv run --no-sync pytest tests/engine/test_live_scope_regression.py -s   # 3회 반복, 회귀셋+미사용셋+통합
MALTEUM_LIVE_REGRESSION=1 MALTEUM_SCOPE_REPEATS=1 MALTEUM_SCOPE_UNSEEN=0 uv run --no-sync pytest tests/engine/test_live_scope_regression.py -s   # 선별용
uv run --no-sync pytest tests/engine/test_live_llm.py -s
APP_LLM_MODEL='' APP_ANSWER_LLM_MODEL='' APP_EMBEDDING_MODEL='' make test   # 저장소 루트
```
