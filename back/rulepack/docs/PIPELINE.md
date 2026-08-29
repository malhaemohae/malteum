# 파이프라인 구조

규정 PDF 에서 팩 JSON 까지. 기준일 2026-08-29.

## 데이터 흐름

```
assets/03_규정문서/*.pdf  (7종)
    │  source_manifest.py    MANIFEST 파싱 · SHA-256 · page_count · 파서 버전 고정
    ▼
구조 JSON
    │  structure.py          OpenDataLoader 로 표 · 병합셀 · 제목 계층 복원 (JDK 21)
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
    │  scripts/load_pack.py  (미구현)
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

테이블은 `back/server/database/entities/pack.py` 가 정의하고 alembic 이 만든다. rulepack 은 `server` 를 import 할 수 없으므로 적재 스크립트는 그 모델을 쓰지 않고 SQL 로 넣는다.

`item_embedding.vector` 에는 차원을 박지 않았다. 계약이 "차원을 팩에 묶는다. 컬럼에 차원을 박으면 교체 때 마이그레이션이 필요해진다"고 정했기 때문이다. 대신 pgvector 인덱스를 못 만들어 지금은 전체 스캔이다. 항목이 수천 건대가 되면 차원별 분리를 다시 본다.
