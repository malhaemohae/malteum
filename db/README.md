# db/

`init.sql`은 postgres 컨테이너 첫 기동 때 한 번 실행된다(pgvector 확장). 스키마 변경은 여기서 하지 않고 `back/`의 alembic 마이그레이션으로 한다.
