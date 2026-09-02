# db/ — 스키마 (ERD)

M1 노순혁 소유. **이 문서가 테이블 구조의 정본이고, 변경은 여기 diff 로 알린다.**
실제 DDL 은 `back/server/database/migrations/` 의 alembic 리비전이며, 이 문서와 리비전은 같은 커밋에서 함께 움직인다.

계약(`back/contracts/`)이 저장물의 모양을 정한다. 이 문서는 그 계약을 postgres 에 어떻게 앉히는지만 적는다.

## 1. 한 장

```mermaid
erDiagram
    rule_packs   ||--o{ pack_embeddings : "팩 1 : 벡터 N"
    sessions     ..o{ session_events  : "세션 1 : 이벤트 N (FK 없음 — D5)"
    session_events ||--o| session_events : "supersedes"

    candidate_approvals {
        text        candidate_id PK "sha256(doc_id:code)[:16]"
        text        doc_id "인덱스"
        text        suggested_code "승인 시점의 항목 코드"
        text        approved_by
        jsonb       edits "검수자가 고친 내용"
        timestamptz approved_at
    }

    rule_packs {
        text        pack_version PK "DEP-2026.08-v4"
        text        product_code
        text        product_name
        text        product_category "deposit | loan"
        timestamptz published_at
        text        published_by
        text        embedding_model "e5-small · bge-m3"
        int         embedding_dim   "384 · 1024"
        jsonb       doc "팩 전체. rulepack.schema.json 정본"
        timestamptz loaded_at
    }

    pack_embeddings {
        bigserial id PK
        text      pack_version FK
        text      item_code
        text      embedding_id "팩의 item.embedding_id (있으면)"
        text      source "item | forbidden_example | risk_example | plain_language | jargon_term"
        int       ordinal
        text      body_text "임베딩 원문"
        vector    embedding "차원 미지정 — D1"
        text      model
        int       dim
    }

    sessions {
        text        session_id PK
        text        mode "live | replay | trace | text"
        text        pack_version
        text        product_code
        text        product_name
        text        customer_type "general | professional"
        text        status "running | ended | aborted | timeout"
        timestamptz started_at
        timestamptz ended_at
        int         duration_ms
        int         met
        int         items_total
        int         violations
        text        source_session_id "mode=trace 재생 대상"
        text        preset_id
    }

    session_events {
        text        event_id PK "ULID"
        text        session_id "FK 없음 — D5"
        int         seq_in_session
        timestamptz occurred_at
        text        pack_version
        text        kind "6종"
        text        supersedes FK "앞선 판정"
        text        schema_version
        jsonb       body "event[kind] 본문"
    }
```

## 2. 테이블

### `session_events` — 정본

**모든 것의 원본.** 화면·리포트·재생·감사가 전부 여기서 나온다. append-only 이며 갱신은 새 행 + `supersedes` 로 한다.

| 컬럼 | 타입 | 근거 |
| --- | --- | --- |
| `event_id` | `text` PK | 봉투. `envelope.wrap` 이 찍는 ULID |
| `session_id` | `text` NOT NULL | `sessions` 로의 FK 를 걸지 않는다 (D5) |
| `seq_in_session` | `int` NOT NULL | `UNIQUE(session_id, seq_in_session)` |
| `occurred_at` | `timestamptz` NOT NULL | |
| `pack_version` | `text` NOT NULL | 이벤트가 낱개로 해석돼야 하므로 모든 행에 (계약 README) |
| `kind` | `text` NOT NULL | `CHECK` — session_started · utterance · verdict · alert · assist · session_ended |
| `supersedes` | `text` NULL → 자기참조 | supersede 되지 않은 마지막 행만 화면·리포트가 읽는다 |
| `schema_version` | `text` NOT NULL | 과거 이벤트 해석용 |
| `body` | `jsonb` NOT NULL | `event[kind]` 본문 |

인덱스: `(session_id, seq_in_session)` · `(supersedes) WHERE supersedes IS NOT NULL`

**본문을 컬럼으로 펼치지 않는 이유.** `events.schema.json` 은 kind 마다 본문이 다르고, 계약이 "필드 **추가는 안전**"이라고 명시한다. 컬럼으로 펼치면 계약에 필드가 하나 늘 때마다 마이그레이션이 생긴다. 봉투만 컬럼으로 뽑아 인덱스하고 본문은 JSONB 로 둔다.

`session_id` 에 **FK 를 걸지 않는다**(D5). `sessions` 는 파생 투영이고 이 표가 정본이다.

**저장하지 않는 것** (기획 5.3): 원본 오디오 · 중간 전사(partial) · 실제 개인정보. 확정 발화만 PII 마스킹 후 `utterance` 본문에 들어간다. **오디오·partial 을 위한 컬럼을 만들지 않는다.** 리포트의 "발화 재생"은 저장된 상담 음성이 아니라 시나리오 오디오(`assets/scenarios/<id>/audio.wav`) 재생이다.

### `sessions` — 파생 투영

**정본이 아니다.** 이벤트를 접으면 전부 다시 만들 수 있다. `/sessions` 목록이 `mode` 필터와 커서 페이지네이션을 요구하고(`api.openapi.yaml`), `status`·`met`·`violations` 를 매 조회마다 접는 것이 낭비라서 투영을 둔다.

`SessionSummary` 의 필드를 그대로 담는다. 인덱스는 `(started_at DESC, session_id)`(커서) · `(mode)`.

`pack_version` 에 **FK 를 걸지 않는다.** 개발·테스트는 `FilePackSource` 로 팩을 파일에서 읽고(`settings.pack_dir`), 그 팩은 DB 에 없다. FK 를 걸면 파일 팩으로 연 세션이 저장 자체를 못 한다.

### `rule_packs` — 불변 발행물

`doc` JSONB 한 칸이 정본이다. 나머지 컬럼은 조회용으로 `doc` 에서 복사한 것이다.

**정규화하지 않는 이유가 둘.**

하나. engine 은 server 를 import 할 수 없다(import-linter 가 강제). M2 의 `PostgresPackSource.read()` 는 `rulepack.schema.json` 을 만족하는 dict 를 돌려줘야 하는데, 통짜 JSONB 면 그게 한 줄로 끝난다:

```sql
SELECT doc FROM rule_packs WHERE pack_version = %s
```

둘. 팩 스키마가 더 커진다. 기획 19장이 계약 C2(조건부 활성 항목)·C3(절차 보조 항목)를 "동결에서 제외"로 남겨뒀고, 이번 v0.4 에서도 `item.type` 에 `risk` 가, 최상위에 `jargon_terms` 가 붙었다. 정규화해두면 팩 스키마가 늘 때마다 마이그레이션을 쓰게 된다. JSONB 면 0 번이다.

UPDATE 하지 않는다. 고칠 일이 생기면 새 `pack_version` 을 발행한다.

### `candidate_approvals` — 사람이 누른 결정

**후보 자체는 저장하지 않는다.** 후보는 M3 의 후보 규칙에서 매번 다시 뜨는 파생물이고(`server/services/candidates.py`), 사람이 누른 승인만이 다시 만들 수 없는 원본이다(AGENTS.md 원칙 3).

`candidate_id` 는 `sha256(doc_id:code)[:16]` 으로 **결정된다.** 무작위로 매기면 파이프라인을 다시 돌릴 때마다 id 가 바뀌어, 어제 승인한 후보가 오늘은 다른 후보가 된다.

`doc_id` 에 FK 를 걸지 않는다. 문서 목록은 발행된 팩의 `sources` 에서 만드는 파생물이라 테이블이 없다.

같은 후보를 두 번 승인하면 **첫 기록의 시각이 그대로 돌아온다(멱등).** 계약이 이 경로에 200 과 400 만 두어 409 를 낼 자리가 없다. 덮어쓰지는 않는다 — 누가 언제 승인했는지가 증빙이라 두 번째 승인자는 기록되지 않는다. 승인 취소 경로는 계약에 아직 없다.

### `pack_embeddings` — L2 의 검색면

벡터 본체는 팩 JSON 에 넣지 않는다(파일이 거대해지고 diff 가 무의미해진다 — `rulepack.schema.json` 주석). 항목뿐 아니라 `forbidden_examples`·`risk_examples`·`plain_language`·`jargon_terms` 도 각각 한 행이 되므로 `source`+`ordinal` 로 출처를 밝힌다.

`UNIQUE(pack_version, item_code, source, ordinal)`.

## 3. 결정

### D1. pgvector 차원 — **차원 미지정 `vector`, 인덱스 없음** (추천)

문제: `rulepack.schema.json` 이 차원을 팩에 묶어놨다("컬럼에 차원을 박으면 교체 때 마이그레이션이 필요해진다"). 그런데 pgvector 는 차원을 박아야 ivfflat·hnsw 인덱스가 걸린다. 그리고 기획 19장이 **e5-small(384) → bge-m3(1024) 교체를 열어뒀다.** 가정이 아니라 예정된 사건이다.

실측한 규모:

| | 값 |
| --- | --- |
| 팩당 항목 | **9개** (required 5 · forbidden 2 · reference 1 · risk 1) |
| 팩당 임베딩 대상 | 항목 9 + forbidden_examples 7 + plain_language 6 + numeric/jargon ≈ **25행** |
| 발행 예정 팩 | 2종 (예적금 중도해지 · 주담대) |
| **총 벡터** | **약 50행** |

50행 × 384차원 = 약 77KB. 순차 스캔 1ms 미만이고, L1+L2 예산은 20ms 다. **HNSW 인덱스가 의미를 갖는 건 수천 행부터다.** 이 규모에서 인덱스는 이득이 없다.

| 안 | 인덱스 | 모델 교체 비용 | 판정 |
| --- | --- | --- | --- |
| **차원 미지정 `vector`** | 불가 (seq scan) | **0** | ✅ 채택 |
| 차원 고정 `vector(384)` | 가능 | 마이그레이션 + 재적재 | 규모상 이득 없음 |
| 차원별 테이블 분리 | 가능 | 교체마다 테이블 추가 | 기획이 피하려던 것 |

교체기에는 384 와 1024 가 **동시에 존재한다**(팩 재발행이 점진적이므로). 단일 테이블 + `dim` 컬럼이 그 기간을 자연스럽게 담는다.

행이 수천 단위로 늘면 그때 `vector(N)` 테이블을 파생으로 추가한다. 지금 미리 만들지 않는다.

### D2. 판정 캐시 — **미정, R2 확인 대기**

기획 11.4: "replay 는 판정 캐시를 쓰므로 심사위원 동시 접속 시에도 두 번째부터 STT·LLM 호출 0." 캐시가 프로세스 메모리면 재시작 때 사라진다. 리스크 6(키·비용 소진)의 대응책이기도 하므로 지속성이 필요할 수 있다.

`DecisionCache` 는 M2(허현준) 소유 Protocol 이고 저장은 M1 땅이다. **테이블이 필요한지 R2 에 확인한 뒤 자리를 잡는다.** 지금 만들지 않는다.

### D3. `documents` 계열 — **후보·승인만 채택 (2026-09-02)**

옛 상태: "REST 표면이라 M1 이지만 내용은 M3 다. 누가 짜는지 정해진 뒤 스키마를 잡는다."

**기획 14장이 이미 배정하고 있었다.** R3(M3)이 "구조 추출 · LLM 추출 · 스팬 대조 · 좌표 · 팩 발행", R4 가 S4 화면, R1 은 게이트웨이다. 11.2 도 "심사위원 업로드 화면(S4)은 **같은 파이프라인을 라이브로 노출**" 이라 M1 이 다시 짜는 그림이 아니다. 미정이 아니라 안 읽은 것이었다.

**넷 중 둘은 M3 를 기다리지 않아도 됐다.** 후보에 필요한 값(코드·이름·타입·요건·근거)이 M3 의 `back/rulepack/config/candidate_rules.json` 에 커밋돼 있고, 근거 대조는 `contracts/find_span.py` 로 직접 뜬다(`server → contracts` 는 허용 import). 실측으로 M3 의 `docs/STATUS.md` 와 판정이 일치했다 — 검증 18 · 자동 폐기 2 · 보류 1(risk).

그래서 `candidate_approvals` 하나만 만든다. 후보는 파생물이라 테이블이 없다.

**남은 둘**(`POST /documents` · `/extraction`)은 OpenDataLoader 구조 추출 산출물이 있어야 하는데 그것은 M3 의 `artifacts/` 에 있고 `.gitignore` 다. 기획 10.1 기본 경로에는 없고 10.2 심화 경로이며, 15장 절삭 순서 4번째("B축 승인 화면")다. **테이블을 미리 만들지 않는다.**

옛 전제 정정: 이 문서가 "S4 가 심사 경로에 실제로 들어가므로 구현은 필수" 라고 적었는데, 기획 10.1 기본 경로 6단계에 문서 업로드가 없다. 필수가 아니라 심화다.

### D4. append-only 강제 — **코드로만**

UPDATE·DELETE 를 막는 트리거를 걸 수 있지만 걸지 않는다. alembic downgrade 와 테스트 정리가 번거로워지고, 저장 경로가 `EventStore.append` 하나뿐이라 코드로 이미 닫혀 있다. 9/4 기능 동결까지의 일정에서 이득보다 마찰이 크다.

### D5. `session_events` → `sessions` FK — **걸지 않는다**

처음에는 `ON DELETE CASCADE` FK 를 걸었다. 저장 계층을 구현하면서 두 가지가 드러났다.

**하나. 정본이 파생물에 매인다.** `sessions` 는 이벤트를 접으면 언제든 다시 만들 수 있는 투영인데,
FK 가 있으면 투영 행이 먼저 있어야 이벤트를 저장할 수 있다. 순서가 거꾸로다.

**둘. 투영을 지우면 정본이 사라진다.** `CASCADE` 라서 `sessions` 한 행을 지우면 그 세션의 이벤트가
통째로 날아간다. 파생물을 다시 만들려다 원본을 잃는 구조다. AGENTS.md 원칙 3
("이벤트가 원본이고 상태는 파생물")과 정면으로 어긋난다.

그래서 FK 를 제거한다. 투영이 없는 이벤트가 생길 수 있지만, 그건 투영을 다시 접으면 메워진다.
반대 방향(이벤트 없는 투영)은 애초에 만들지 않는다.

`supersedes` 자기참조 FK 는 유지한다. 정본 안에서의 참조이고 갱신 사슬이 끊기면 안 된다.
`pack_embeddings → rule_packs` 의 CASCADE 도 유지한다. 벡터는 팩의 파생물이므로 방향이 맞다.

## 4. 첫 리비전에 들어가는 것

`sessions` · `session_events` · `rule_packs` · `pack_embeddings` 넷.

`CREATE EXTENSION IF NOT EXISTS vector` 를 리비전 맨 앞에 둔다. compose 는 `db/init.sql` 이 만들어주지만, 로컬 postgres 에 직접 붙는 경우가 있다.

D2 는 결정된 뒤 별도 리비전으로 붙인다. **빈 테이블을 미리 만들지 않는다**(AGENTS.md 작업 방식).

## 5. 이후 리비전

`0002_candidate_approvals` — `candidate_approvals` (D3). 후보 조회·승인 REST 두 경로가 서면서 붙었다.
