# 파이프라인 구조

규정 PDF 에서 팩 JSON 까지. 기준일 2026-08-29.

## 데이터 흐름

```
assets/03_규정문서/*.pdf  (7종)
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
    │  scripts/load_pack.py  팩 JSON → SQL. 임베딩은 어댑터가 만든다
    ▼
postgres  pack · pack_item · item_embedding
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

- import 는 `contracts` 와 DB 드라이버만. `server` · `engine` 은 금지(import-linter 가 강제)
- 인용 좌표는 `contracts/find_span.py` 하나로 뜬다. 다른 구현을 쓰면 `validate.py` 3층에서 실패하는 팩이 나온다
- 팩은 불변 발행물. 수정하지 않고 새 `pack_version` 을 낸다. 항목 `code` 는 버전이 올라가도 유지한다
- 근거 `span` 이 원문에 실재하지 않는 항목은 팩에 넣지 않는다(P4)

## 실행

```bash
cd back
uv run python -m rulepack.cli build            # 후보 생성
uv run python -m rulepack.cli verify --strict  # 결정성 · 고정 의존성 · java · 계약 검증
```

`verify` 는 `build` 를 임시 폴더에 두 번 돌려 결과가 같은지 비교한다. 그래서 실제 출력 경로에 쓰는 구간은 `build` 로 따로 확인한다. CI 가 둘 다 돌린다.

## DB 적재

테이블은 M1 이 정의한다(`back/server/database/entities/rulepack.py` · 근거는 `db/SCHEMA.md`). `rule_packs.doc` JSONB 한 칸이 팩 정본이고 나머지 열은 조회용 사본이다. 적재 스크립트는 그 모델을 import 하지 않고 SQL 로 넣는다. 발행 도구가 상담 서버의 모델에 붙으면 두 배포가 한 몸이 되기 때문이다. `scripts/` 는 import-linter 의 `root_packages` 밖이라 린터가 막지는 않고, 설계 의도로 지키는 경계다.

항목을 열로 펼치지 않는 이유가 둘이다. M2 가 `SELECT doc` 한 줄로 팩을 그대로 돌려받아야 하고, 열로 펼치면 `published_at` 이 timestamptz 를 왕복하며 표기가 바뀌어(`2026-08-30T00:00:00Z` → `2026-08-30 00:00:00+00`) `pack_sha256` 대조가 깨진다. JSONB 는 바이트를 보존한다. M3 가 따로 만들었던 `pack`·`pack_item`·`item_embedding` 은 이 검증을 통과하지 못해 2026-08-30 에 걷어냈다.

`pack_embeddings` 는 항목 하나당 여러 행이 된다. 금지·위험 예시와 쉬운 말이 각각 검색면이 되어야 L2 가 발화를 넓게 잡는다. 예금 팩 9항목이 24행이 된다. `jargon_terms` 는 넣지 않는다. 용어 밀도 게이지는 목록 대조로만 세므로 벡터가 필요 없고, 팩 전역이라 붙일 `item_code` 도 없다.

발행은 `publish` 가 `artifacts/rulepack_<version>.json` 을 쓴다. M2 는 이 파일 이름 하나로 M3 와 만난다(`engine/adapters/pack_source/file.py`). 서로의 코드를 안 보고도 연결되는 지점이라 이름이 바뀌면 조용히 끊긴다.

적재는 `scripts/load_pack.py` 가 한다.

```bash
python scripts/load_pack.py <compile 산출물> [--replace] [--dry-run] [--unsigned]
```

`compile` 이 낸 envelope 만 받는다. 받으면 `compiler_attestation`(HMAC-SHA256: 비밀키로 만든 짧은 지문)과 `pack_sha256` 을 둘 다 다시 대조한다. 발행과 적재가 같은 검사를 거치게 하는 것이 목적이다.

`publish` 가 쓰는 `rulepack_<version>.json` 은 팩 본문만이라 서명이 없다. 그것을 그대로 받으면 발행 시점부터 DB 에 들어가기 전까지의 구간(아티팩트 저장소·공유 폴더·수동 복사)에서 금액 한 자리를 고쳐도 막을 방법이 없다. 팩은 창구 판정의 기준이라 그 순간 시스템이 틀린 것을 가르치게 된다. 그래서 서명 없는 입력은 `--unsigned` 를 명시해야 들어가고, 그 플래그는 개발용이다.

`verify` 의 dry-run 산출물은 `production_publishable` 이 거짓이라 거절한다. 같은 `pack_version` 을 두 번 넣는 것도 막는다. 팩은 불변 발행물이라 새 버전을 내는 것이 원칙이고, 덮어쓰려면 `--replace` 를 명시해야 한다. 적재에는 `RULEPACK_APPROVAL_HMAC_KEY` 가 필요하다(`--unsigned` 일 때는 불필요).

`scripts/seed_pack.py`(M1) 도 같은 테이블에 넣지만 벡터를 만들지 않는다. `load_pack.py` 가 무결성 검증·임베딩 생성까지 하는 상위집합이라, 둘을 하나로 합칠지는 M1 과 협의할 사항이다.

### 로컬 검증 뒤 정리

적재를 시험해 보려고 넣은 팩은 끝나면 지운다. 안 지우면 다음 원천 교체 뒤에도 옛 팩이 DB 에 남고, `postgres.py` 어댑터가 붙는 순간 만료된 기준을 읽게 된다. 실제로 2026-08-30 에 심의 만료 원천으로 만든 항목 3개짜리 팩이 남아 있었다.

`published_by` 로 구분한다. 사람이 승인한 발행물이 아니면 `local-verification` 처럼 그렇게 적고, 확인이 끝나면 지운다. FK 가 `RESTRICT` 라 자식부터 지워야 한다.

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

`item_embedding.vector` 에는 차원을 박지 않았다. 계약이 "차원을 팩에 묶는다. 컬럼에 차원을 박으면 교체 때 마이그레이션이 필요해진다"고 정했기 때문이다. 대신 pgvector 인덱스를 못 만들어 지금은 전체 스캔이다. 항목이 수천 건대가 되면 차원별 분리를 다시 본다.
