#!/usr/bin/env bash
# contracts/ 스키마 → server/generated/{ws,events,api}.py
#   ws·events : scripts/gen_models.py (if/then 분기 평탄화)
#   api       : datamodel-codegen (OpenAPI components)
# 생성 파일은 수동 편집 금지. `--check` 는 재생성 후 git diff 가 없는지 검사한다(CI).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="server/generated"
mkdir -p "$OUT"

uv run python scripts/gen_models.py "$OUT"
uv run datamodel-codegen --input contracts/api.openapi.yaml --input-file-type openapi \
  --output "$OUT/api.py" \
  --output-model-type pydantic_v2.BaseModel --target-python-version 3.12 \
  --disable-timestamp --use-annotated --use-schema-description --field-constraints \
  --use-standard-collections --use-union-operator --collapse-root-models \
  --enum-field-as-literal all --formatters builtin 2>/dev/null
cat > "$OUT/__init__.py" <<'PY'
"""contracts/ 스키마에서 생성한 런타임 모델. scripts/gen_models.sh 로만 갱신한다. 수동 편집 금지."""
PY
uv run ruff format --quiet "$OUT"

if [[ "${1:-}" == "--check" ]]; then
  if git diff --quiet -- "$OUT" && [[ -z "$(git ls-files --others --exclude-standard -- "$OUT")" ]]; then
    echo "generated/ 최신"
  else
    git --no-pager diff -- "$OUT"
    echo "generated/ 가 스키마와 다르다. scripts/gen_models.sh 를 실행해 커밋하라" >&2
    exit 1
  fi
fi
