.PHONY: up seed down logs test lint gen

up:            ## postgres + server
	docker compose up --build -d

seed:          ## 저장소의 팩(contracts/fixtures)·시연 A 이벤트를 DB 에 적재. make up 뒤 한 번, 팩 재발행 뒤 다시
	docker compose exec server python scripts/load_pack.py --replace --unsigned
	docker compose exec server python scripts/seed_session.py --replace

down:
	docker compose down

logs:
	docker compose logs -f server

lint:          ## ruff · import-linter · 생성 파일 최신 여부
	cd back && uv run ruff check . && uv run ruff format --check . && uv run lint-imports && scripts/gen_models.sh --check

test: lint     ## lint 후 pytest
	cd back && uv run pytest -q

gen:           ## contracts 스키마 → server/generated
	cd back/ && scripts/gen_models.sh
