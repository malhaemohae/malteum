# back/ — 파이썬 루트

uv 프로젝트. `server`·`engine`·`rulepack`은 이 폴더를 cwd로 import한다(`uv run ...`을 여기서 실행).

## 명령

```bash
uv sync                      # 의존성
uv run ruff check . && uv run ruff format --check .
uv run lint-imports          # 모듈 경계
uv run pytest                # tests/{server,engine,rulepack}
scripts/gen_models.sh        # contracts 스키마 → server/generated/  (--check: CI)
```

## 경계 (pyproject `[tool.importlinter]`)

`server → engine, contracts` / `engine → contracts` / `rulepack → contracts`. 그 밖의 import는 실패한다. `contracts/`는 `__init__` 없는 namespace 패키지이며 파일을 얹지 않는다(임한빈 원본, 8/28 동결).

## 생성 파일

`server/generated/{ws,events,api}.py`는 스키마의 파생물이다. 수동 편집하지 않고 스키마를 고친 뒤 `scripts/gen_models.sh`를 돌린다. 축↔상태 같은 교차 필드 제약은 생성 모델에 없으므로 경계에서 `jsonschema`로 원본 스키마를 함께 검증한다(`server/ws/protocol.py`).
