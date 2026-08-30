# back/rulepack — M3 rulepack (임한빈)

규정 PDF → `contracts/rulepack.schema.json`을 만족하는 팩 JSON → postgres(`rule_packs`·`pack_embeddings`) 적재. 테이블은 M1 이 `db/SCHEMA.md` 에서 정의하고, M3 는 그 위에 넣는 쪽이다. 파이프라인 설계·폴더 구성·권한은 담당자가 정한다.

## 허용 import

`contracts`와 DB 드라이버(psycopg·sqlalchemy)만. `server`·`engine`은 금지.

## 규칙

- 적재는 REST가 아니라 스크립트(`scripts/load_pack.py`)로 한다. 서버가 떠 있을 필요가 없다.
- 인용 좌표는 `contracts/find_span.py` 하나로 뜬다. 다른 구현을 쓰면 `validate.py` 3층에서 실패하는 팩이 나온다.
- 팩은 불변 발행물. 수정하지 않고 새 `pack_version`을 낸다. 항목 `code`는 버전이 올라가도 유지한다.
- 근거 `span`이 원문에 실재하지 않는 항목은 팩에 넣지 않는다(P4).

## 문서

코드를 고치면 해당 문서를 같은 커밋에서 함께 갱신한다. 낡은 문서는 틀린 정보보다 나쁘다.

| 문서 | 무엇 | 언제 고치나 |
| --- | --- | --- |
| `docs/STATUS.md` | 후보 판정 현황과 남은 막힘 | 발행 가능·차단 건수가 바뀔 때 |
| `docs/PIPELINE.md` | 데이터 흐름과 모듈별 책임 | 단계를 넣거나 뺄 때 |
| `docs/SOURCES.md` | 원천 감사 판정과 교체 절차 | 원천을 교체하거나 판정이 바뀔 때 |
| `docs/CONTRACT_GAPS.md` | 계약이 침묵해 막힌 지점 | 공백이 생기거나 메워질 때 |

날짜가 박힌 것(`artifacts/source_refresh_*.json`)은 그 시점의 스냅샷이라 고치지 않고 새 파일로 쌓는다.
