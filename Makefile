.PHONY: up down logs test lint gen

up:            ## postgres + server
	docker compose up --build -d

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
