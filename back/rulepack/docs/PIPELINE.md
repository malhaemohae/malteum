# 파이프라인 구조

규정 PDF 에서 팩 JSON 까지. 기준일 2026-08-30.

## 데이터 흐름

```
assets/03_규정문서/*.pdf  (10종. 08 은 웹 공시 스냅샷, 09·10 은 2026-09-05 추가)
    │  source_manifest.py    MANIFEST 파싱 · SHA-256 · page_count · 파서 버전 고정
    ▼
구조 JSON
    │  structure.py          OpenDataLoader 로 표 · 병합셀 · 제목 계층 복원 (JDK 17+)
    ▼
상품별 chunk
    │  pipeline.py           config/candidate_rules.json 을 근거로 후보 생성
    │  adapters.py           결정적 fake 와 OpenAI 호환 구조화 출력. 항목별 실패 격리
    ▼
CandidateItem
    │  contracts/find_span.py   인용 문자열 → page · 문자 좌표 (P4 의 기계적 관문)
    │  pipeline.py             중복 · 숫자 · 최신성 관문
    ▼
RC + 리뷰 큐  ← 자동 실행의 정상 종점
    │  compiler.py           원천 · 최신성 재검증 · RC digest · HMAC 승인 결합
    ▼
attested 팩 JSON
    │  scripts/load_pack.py  팩 JSON → M1 의 ORM 모델. 임베딩은 어댑터가 만든다
    ▼
postgres  rule_packs(doc 정본) · pack_embeddings(검색면)
```

## 모듈별 책임

| 파일 | 하는 일 |
| --- | --- |
| `paths.py` | 배치 해석. 개인 작업장과 팀 레포 두 구조를 모두 지원 |
| `source_manifest.py` | 원천 고정. 해시가 어긋나면 이후 단계가 전부 막힌다 |
| `structure.py` | OpenDataLoader 구조 추출 |
| `adapters.py` | 후보 추출 어댑터. 항목 하나가 실패해도 나머지는 계속 |
| `pipeline.py` | 후보 생성 · exact span 단일성 · page · bbox · 최신성 · 리뷰 상태 판정 |
| `compiler.py` | 재검증 · 승인 서명 확인 · JSON Schema 컴파일 · 원자적 불변 발행 |
| `cli.py` | `build` → `verify` → `compile` → `publish` |

## 경계

- `back/rulepack/` 안에서는 import 가 `contracts` 와 DB 드라이버만. `server` · `engine` 은 금지(import-linter 가 강제)
- 적재 스크립트는 `back/scripts/` 라 그 계약 밖이고, M1 의 테이블 모델을 그대로 쓴다
- 인용 좌표는 `contracts/find_span.py` 하나로 뜬다. 다른 구현을 쓰면 `validate.py` 3층에서 실패하는 팩이 나온다
- 팩은 불변 발행물. 수정하지 않고 새 `pack_version` 을 낸다. 항목 `code` 는 버전이 올라가도 유지한다
- 근거 `span` 이 원문에 실재하지 않는 항목은 팩에 넣지 않는다(P4)
- 숫자 사실(`numeric_facts`)은 자기 `evidence` 를 둘 수 있다. 없으면 항목 근거를 물려받고, 있으면 `find_span` 유일성과 bbox 만 검사한다(chunk 지원 검사 없음). 비율·산식(`약정이율×0.5`)은 숫자 사실로 두지 않고 L1 정규식 + L3 판단에 맡긴다

## 실행

```bash
cd back
uv run python -m rulepack.cli build            # 후보 생성
uv run python -m rulepack.cli verify --strict  # 결정성 · 고정 의존성 · java · 계약 검증
```

`verify` 는 `build` 를 임시 폴더에 두 번 돌려 결과가 같은지 비교한다. 그래서 실제 출력 경로에 쓰는 구간은 `build` 로 따로 확인한다. CI 가 둘 다 돌린다.

## DB 적재

테이블은 M1 이 정의한다(`back/server/database/entities/rulepack.py` · 근거는 `db/SCHEMA.md`). `rule_packs.doc` JSONB 한 칸이 팩 정본이고 나머지 열은 조회용 사본이다. 적재 스크립트는 그 모델을 그대로 쓴다. 열을 SQL 로 다시 적으면 계약이 늘 때 스크립트가 조용히 뒤처지고, nullable 열이 추가되면 아무 테스트도 안 깨진 채 그 열만 null 로 남는다. `scripts/` 는 import-linter 의 `root_packages` 밖이라 이 import 는 모듈 경계를 어기지 않는다. 대가는 스크립트가 `server` 패키지에 묶이는 것인데, 발행 도구를 따로 배포할 계획이 없어 지금은 지불할 만하다.

항목을 열로 펼치지 않는 이유가 둘이다. M2 가 `SELECT doc` 한 줄로 팩을 그대로 돌려받아야 하고, 열로 펼치면 `published_at` 이 timestamptz 를 왕복하며 표기가 바뀌어(`2026-08-30T00:00:00Z` → `2026-08-30 00:00:00+00`) `pack_sha256` 대조가 깨진다. JSONB 는 바이트를 보존한다.

`pack_embeddings` 는 항목 하나당 여러 행이 된다. 금지·위험 예시와 쉬운 말이 각각 검색면이 되어야 L2 가 발화를 넓게 잡는다. 예금 팩 9항목이 29행이 된다(2026-09-02 예시 보강 반영 기준). `jargon_terms` 는 넣지 않는다. 용어 밀도 게이지는 목록 대조로만 세므로 벡터가 필요 없고, 팩 전역이라 붙일 `item_code` 도 없다.

발행은 `publish` 가 `artifacts/rulepack_<version>.json` 을 쓴다. M2 는 이 파일 이름 하나로 M3 와 만난다(`engine/adapters/pack_source/file.py`). 서로의 코드를 안 보고도 연결되는 지점이라 이름이 바뀌면 조용히 끊긴다.

적재는 `scripts/load_pack.py` 가 한다. 배포 절차에서는 저장소 루트의 `make seed` 가 이 스크립트(fixtures 전부, `--replace --unsigned`)와 `seed_session.py` 를 한 번에 돈다.

```bash
python scripts/load_pack.py <compile 산출물> [--replace] [--dry-run] [--unsigned]
```

`compile` 이 낸 envelope 만 받는다. 받으면 `compiler_attestation`(HMAC-SHA256: 비밀키로 만든 짧은 지문)과 `pack_sha256` 을 둘 다 다시 대조한다. 발행과 적재가 같은 검사를 거치게 하는 것이 목적이다.

`publish` 가 쓰는 `rulepack_<version>.json` 은 팩 본문만이라 서명이 없다. 그것을 그대로 받으면 발행 시점부터 DB 에 들어가기 전까지의 구간(아티팩트 저장소·공유 폴더·수동 복사)에서 금액 한 자리를 고쳐도 막을 방법이 없다. 팩은 창구 판정의 기준이라 그 순간 시스템이 틀린 것을 가르치게 된다. 그래서 서명 없는 입력은 `--unsigned` 를 명시해야 들어가고, 그 플래그는 개발용이다.

`verify` 의 dry-run 산출물은 `production_publishable` 이 거짓이라 거절한다. 같은 `pack_version` 을 두 번 넣는 것도 막는다. 팩은 불변 발행물이라 새 버전을 내는 것이 원칙이고, 덮어쓰려면 `--replace` 를 명시해야 한다. 적재에는 `RULEPACK_APPROVAL_HMAC_KEY` 가 필요하다(`--unsigned` 일 때는 불필요).

적재하는 길은 이 스크립트 하나뿐이다. 같은 테이블에 서로 다른 방식으로 넣으면 어느 쪽으로 넣었느냐에 따라 `pack_embeddings` 가 비거나 차서 L2 검색이 되고 안 되고가 갈린다. 에러가 아니라 결과가 조용히 비는 종류라 원인을 찾기 어렵다. 넣기 전에 계약 스키마도 다시 본다. 개발용으로 서명 없이 넣을 때는 `--unsigned` 를 쓴다.

```bash
python scripts/load_pack.py                      # pack_dir 의 rulepack_*.json 전부 (--unsigned 필요)
python scripts/load_pack.py DEP-2026.08-v4       # 버전 지정
python scripts/load_pack.py artifacts/compiled_DEP-2026.08-v4.json   # envelope
```

### 로컬 검증 뒤 정리

적재를 시험해 보려고 넣은 팩은 끝나면 지운다. **DB 의 팩이 파일보다 우선하기 때문이다.** `server/services/pack_source.py` 의 `DbThenFilePackSource` 가 DB 를 먼저 보고, 없을 때만 `settings.pack_dir` 의 파일로 내려간다. 그래서 검증용 팩을 남겨 두면 fixture 파일을 아무리 고쳐도 상담 세션 화면은 DB 의 옛 팩을 보여준다. 에러가 아니라 조용히 옛 값이 나오는 종류라 원인을 찾기 어렵다.

2026-08-30 에 실제로 확인했다. DB 쪽 팩의 쉬운 말만 바꾸고 서버를 새로 띄우자 WS 세션이 그 문장을 그대로 내보냈다. 같은 날 심의 만료 원천으로 만든 항목 3개짜리 팩이 남아 있었는데, 그것도 이 경로로 창구 화면에 나갈 수 있었다.

`published_by` 로 구분한다. 사람이 승인한 발행물이 아니면 `local-verification` 처럼 그렇게 적고, 확인이 끝나면 지운다. 임베딩은 FK 가 `CASCADE` 이고 `RulePack.embeddings` 가 `delete-orphan` 이라 머리만 지우면 따라 간다.

```sql
delete from rule_packs where pack_version = '<버전>';  -- pack_embeddings 는 CASCADE
```

## 임베딩

`embedding.py` 의 `EmbeddingModel` 을 따르는 구현이 벡터를 만든다.

| 구현 | 쓰는 곳 |
| --- | --- |
| `E5SmallEmbedding` | 운영. `intfloat/multilingual-e5-small` (117M · 384차원 · MIT) |
| `DeterministicFakeEmbedding` | 모델 없이 경로만 돌려볼 때 |

나중에 외부 임베딩 API 로 갈아탈 때도 같은 Protocol 을 구현하면 되고, 팩 구조와 적재·테이블은 손대지 않는다. 적재는 팩이 적은 `embedding.model` 로 구현을 고르므로, 모르는 이름이면 멈춘다.

### 왜 이 모델인가

기획안 375줄이 정한 것이고, 2026-08-30 에 실측으로 확인했다.

| 항목 | 실측 |
| --- | --- |
| 문장 1개 인코딩 (CPU, 배치 없음) | 중앙값 7.0ms · p95 8.9ms · 최대 10.0ms |
| 기획안 L2 지연 예산 | 5~20ms. 통과 |
| 검색 1순위 적중 | 대출 발화 5건 중 4건 |
| 설치 용량 | `.venv` 150MB → 887MB (CPU 휠) |

한국어 정확도 1위는 KURE-v1(NDCG@10 0.695, 568M)이지만 bge-m3 계열이라 CPU 에서 30ms 를 넘어 지연 예산을 못 맞춘다. L2 는 프리필터이고 최종 판정권이 L3 에 있으므로 정확도보다 지연을 지키는 쪽을 골랐다.

빗나간 1건은 "금리 깎아달라고 할 수 있나요"였는데, 대상인 `LOAN-RDR-001` 이 `evidence_scope_mismatch` 로 아직 발행 대상이 아니라 후보에 없었다. 모델 문제가 아니다.

### CPU 로 고정한 이유

벡터를 만드는 곳(M3 오프라인 배치)과 쓰는 곳(M2 실시간 L2)이 다르다. 쓰는 쪽이 자체 서버라 GPU 를 가정할 수 없고, 만드는 쪽만 GPU 를 쓰면 부동소수점 연산 순서가 달라져 `verify --strict` 의 결정적 재실행 검사가 흔들린다. CI 에도 GPU 가 없다.

### 접두어

E5 계열은 입력에 `query:` 또는 `passage:` 를 붙여 학습했다. 팩 항목은 검색 대상이라 `passage:`, 실시간 발화는 `query:` 를 쓴다. 빼면 학습 분포와 어긋나 유사도가 나빠진다.

팩의 `embedding.model` · `dim` 은 **실제로 벡터를 만든 구현이 스스로 밝힌 값**이다. 상수로 박아 두면 벡터를 만든 적도 없는 모델 이름이 팩에 남는다. 2026-08-29 이전이 `intfloat/multilingual-e5-small` 을 그렇게 적고 있었다.

무엇을 인코딩하는가는 `embedding_text` 가 정한다. 항목 이름 · 요구 요건 · 쉬운 말을 합치고 근거 원문은 넣지 않는다. 법령 문장은 표현이 상담 발화와 멀어 검색을 흐린다.

### L2 골든셋 평가

검색 품질은 `config/golden_utterances.json` 에 박힌 (발화, 기대 항목) 쌍으로 잰다. 2026-09-01 엔진 팀 실측에서 e5-small 단독은 짧은 구어 발화와 항목 설명의 유사도가 0.77~0.87 좁은 띠에 몰려 무관 발화가 분리되지 않았는데, 그 실험이 일회성으로 끝나지 않게 하는 장치다. 모델·검색 방식을 바꾸면 이걸 다시 돌려 전후를 비교한다.

```bash
cd back
uv run python scripts/eval_l2_goldenset.py                   # artifacts 의 발행 팩 전부, e5
uv run python scripts/eval_l2_goldenset.py --model fake      # 모델 없이 경로 확인(CI 스모크)
uv run python scripts/eval_l2_goldenset.py <팩.json> --engine  # 엔진 L2(자모 trigram + dense 융합) 경로로
```

기본 실행은 dense 단독이다. `--engine` 은 서비스가 실제로 쓰는 `engine/tiers/l2/searcher.py`(L0 정규화 → 자모 trigram 덮임 주 신호, dense 는 항목 간 분산이 있을 때만 보조) 그대로 순위를 매긴다. 검색 방식이나 검색면을 바꿀 때는 둘을 나란히 재서, dense 단독 수치가 아니라 엔진 경로 수치로 판단한다.

지표는 top-1 정답률 · recall@k(기대 항목이 상위 k 후보에 드는 비율) · 관련/무관 점수 분리다. L2 는 프리필터라 최종 판정권이 L3 에 있으므로 recall@k 와 분리력이 판단 기준이고 top-1 은 참고치다. 골든셋의 정합(없는 코드 기대, 금지 항목 누락, 검색면이 `scripts/load_pack.py` 의 `rows` 와 어긋남)은 `tests/rulepack/test_golden_utterances.py` 가 막는다.

2026-09-03 baseline (e5-small 단독 · top-k 3 · 발행 가능 전 항목, 예금은 `contracts/fixtures/` 의 v4 팩 · 대출은 v5 팩. 2026-09-02 측정치는 대출 8항목 synthetic 팩 기준 6/8 · 7/8 이었고, 금지 예시 보강·숫자 사실 추가·금리인하요구권 발행·쉬운 말 2건 보강·골든셋 2건 추가 뒤 다시 잰 값이 아래):

| 팩 | top-1 | recall@3 | 관련 top1 대역 | 무관 top1 대역 |
| --- | ---: | ---: | --- | --- |
| 예금 9항목 | 7/10 | 8/10 | 0.846~0.944 | 0.806~0.822 |
| 대출 9항목 | 7/10 | 10/10 | 0.845~0.954 | 0.793~0.815 |

recall@3 실패는 `DEP-PRO-001`(6위) · `DEP-LIM-001`(4위) 둘. 대출은 쉬운 말에 골든 발화의 어휘("마음이 바뀌면 … 무를", "갚는 날을 넘기면")를 넣어 `WDR`·`ARR` 이 상위 3 안으로 들어왔다. 이 방식은 골든셋 어휘를 검색면에 심는 것이라 그 발화에는 확실히 듣지만 일반화 지표로는 낙관적이다. 단정 발화 패러프레이즈(`loan-ban1-fixed-rate-assertion`)가 `LOAN-RSK-001` 에 1위를 내주는 것은 그대로. 관련 최저와 무관 최고의 간격이 0.02 안팎이라 절대 점수 임계값 게이트는 아직 못 세운다. 엔진의 자모 trigram 융합 같은 검색 방식 변경은 이 표와 같은 조건으로 다시 재서 대조한다.

같은 팩·골든셋을 `--engine` 으로 잰 값(2026-09-03). 무관 발화 4건은 두 팩 모두 전 항목 0.000 이라 분리가 완전하다. dense 단독의 "간격 0.02" 문제는 엔진 경로에는 없다.

| 팩 | top-1 | recall@3 | 남은 실패 |
| --- | ---: | ---: | --- |
| 예금 9항목 | 6/10 | 9/10 | `dep-doc1-documents`: trigram 0 이고 dense 는 분산 부족으로 버려져 순위 자체가 없음(검색면에 구어 표면이 없다) |
| 대출 9항목 | 8/10 | 9/10 | `loan-ban1-fixed-rate-assertion`: `LOAN-BAN-001` 4위(0.3대). 단정 발화 패러프레이즈는 예시 문장과 글자가 안 겹친다 |

금지 발언 패러프레이즈가 L2 를 못 넘는 구멍을 L3 쪽에서 막는 안("refine 이 도는 은행원 발화에는 아직 violated 가 아닌 금지 항목을 전부 후보에 넣는다") 은 2026-09-03 에 실물 LLM(`tests/engine/test_live_llm.py`, qwen3-8b) 으로 재 보고 보류했다. 후보에 `DEP-BAN-001` 이 같이 들어가자 "중도해지하시면 이자가 좀 줄어듭니다" 의 `DEP-INT-002` partial 판정에서 빠진 요소가 둘에서 하나(`차감률 또는 산출식`)로 줄었고, 2회 반복·시스템 프롬프트 지시 추가·금지 항목을 별도 `forbidden_watch` 키로 분리한 변형 모두 같은 결과였다. 금지 항목이 프롬프트에 있는 것만으로 필수 항목의 요소 판정이 흔들린다는 뜻이라, 상시 포함은 프롬프트 구조나 모델을 바꾼 뒤 같은 케이스로 다시 재고 넣는다.

**팩을 재발행하면 시연 fixture 를 다시 돌려 본다.** 금지 예시를 보강할수록 은행원의 정정 대사(`assets/scenarios/SCRIPT.md` 4.2)가 예시와 비슷해져 재경보가 뜰 수 있다. `uv run python scripts/gen_scenario_trace.py ../assets/scenarios/preset-dep-a/script.json --out contracts/fixtures/events_scenario_a.json` 을 돌려 요약의 경보 수(현재 3)와 위반 수(1)가 그대로인지 보고, `contracts/validate.py` 를 통과시킨 뒤 발행한다.

재현 조건 세 가지를 지켜야 이 표와 대조가 된다.

- **팩 경로를 명시한다.** 예금은 `contracts/fixtures/rulepack_DEP-2026.08-v4.json`, 대출은 `contracts/fixtures/rulepack_LOAN-2026.08-v6.json`. 인자 없는 기본 실행은 `rulepack/artifacts/` 의 로컬 팩을 집는데, 그 폴더에는 옛 3항목짜리 검증용 팩이 남아 있을 수 있어 수치가 통째로 어긋난다
- **측정 검색면은 `pack_embeddings` 기준이다**(예시·쉬운 말마다 행 하나, 항목 점수는 행 최고점). 엔진의 `MemoryVectorIndex` 는 항목 전체를 한 문자열로 합쳐 벡터 하나만 만들므로(`engine/adapters/vector_index/memory.py` 의 `item_text`) 이 표의 수치가 그 경로로 그대로 옮겨지지 않는다. 두 검색면이 통일되기 전까지 이 표는 행 단위 검색면의 수치다
- `DEP-BAN-001` 예시 보강(9/1) 후 "만기 지나도 금리 그대로예요"가 1위(0.913)인 것은 골든 발화와 예시 문장이 거의 같아서다. 이 케이스는 예시가 검색면에 실렸는지의 확인용이고, 일반화(다르게 표현한 위반 발화)는 별도 패러프레이즈 케이스가 필요하다

`pack_embeddings.embedding` 에는 차원을 박지 않았다. 계약이 "차원을 팩에 묶는다. 컬럼에 차원을 박으면 교체 때 마이그레이션이 필요해진다"고 정했기 때문이다. 대신 pgvector 인덱스를 못 만들어 지금은 전체 스캔이다. M1 이 `db/SCHEMA.md` 에서 규모를 실측했다. 팩당 약 29행이라 인덱스가 의미를 갖는 수천 행대와는 거리가 멀다. e5-small(384)에서 bge-m3(1024)로 갈아타는 기간에는 두 차원이 함께 존재한다.
