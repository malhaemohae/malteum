# back/rulepack — M3 rulepack (임한빈)

규정 PDF → `contracts/rulepack.schema.json`을 만족하는 팩 JSON → postgres(`pack`·`pack_item`·`item_embedding`) 적재. 파이프라인 설계·폴더 구성·권한은 담당자가 정한다.

## 허용 import

`contracts`와 DB 드라이버(psycopg·sqlalchemy)만. `server`·`engine`은 금지.

## 규칙

- 적재는 REST가 아니라 스크립트(`scripts/load_pack.py`)로 한다. 서버가 떠 있을 필요가 없다.
- 인용 좌표는 `contracts/find_span.py` 하나로 뜬다. 다른 구현을 쓰면 `validate.py` 3층에서 실패하는 팩이 나온다.
- 팩은 불변 발행물. 수정하지 않고 새 `pack_version`을 낸다. 항목 `code`는 버전이 올라가도 유지한다.
- 근거 `span`이 원문에 실재하지 않는 항목은 팩에 넣지 않는다(P4).
