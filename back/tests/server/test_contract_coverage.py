"""계약 REST 경로 중 무엇이 서 있고 무엇이 아직 없는지, 기계가 세게 한다.

숫자를 사람이 세어 보고서에 적으면 틀린다 — 기획 문서의 "18 경로" 는 계약이 20 개로
늘어난 뒤에도 그대로 남아 있었다. 여기서 세면 계약에 경로가 하나 붙는 순간 이 테스트가
먼저 말한다.

`MISSING` 은 "아직 안 만든 것" 의 명단이다. 하나를 구현하면 이 목록에서 지워야 테스트가
통과한다 — 지우는 행위가 곧 완료 기록이 된다.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from server.main import create_app

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"

# 아직 서지 않은 계약 경로.
#
# 앞의 둘은 OpenDataLoader 구조 추출 산출물이 있어야 하는데 그것이 M3 의 `artifacts/` 에
# 있고 `.gitignore` 라 서버에 없다. 기획 14장이 구조 추출을 R3 에 배정했다.
# `report.pdf` 는 기획 8.2 가 R4 에 배정했다.
#
# 후보 조회·승인은 여기서 빠졌다 — 후보에 필요한 값이 M3 의 `config/candidate_rules.json`
# 에 커밋돼 있어 M3 를 기다리지 않고 섰다(`services/candidates.py`).
MISSING = {
    ("POST", "/documents"),
    ("GET", "/documents/{doc_id}/extraction"),
    ("GET", "/sessions/{session_id}/report.pdf"),
}

PREFIX = "/api"  # 계약 servers[0].url


def _shape(method: str, path: str) -> tuple[str, str]:
    """경로 변수 이름은 서로 달라도 같은 경로다. `{}` 로 눌러서 견준다."""
    return method.upper(), re.sub(r"\{[^}]+\}", "{}", path)


def _contract_paths() -> set[tuple[str, str]]:
    spec = yaml.safe_load((CONTRACTS / "api.openapi.yaml").read_text(encoding="utf-8"))
    return {
        _shape(method, path)
        for path, operations in spec["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }


def _served_paths() -> set[tuple[str, str]]:
    """앱이 스스로 낸 OpenAPI 를 읽는다. `app.routes` 는 fastapi 버전에 따라 중첩돼
    평평하게 훑기 어렵고, 어차피 프런트가 보는 것도 이 문서다."""
    served = set()
    for path, operations in create_app().openapi()["paths"].items():
        if not path.startswith(PREFIX):
            continue  # ws 엔드포인트와 /docs 는 이 계약의 paths 가 아니다
        for method in operations:
            served.add(_shape(method, path[len(PREFIX) :]))
    return served


def test_no_route_outside_the_contract():
    """계약에 없는 경로를 서버가 열어 두면, 프런트가 계약 밖 API 에 기대게 된다."""
    extra = _served_paths() - _contract_paths()
    assert not extra, f"계약에 없는 경로: {sorted(extra)}"


def test_missing_list_matches_reality():
    """명단이 실물과 어긋나면 — 만들었는데 안 지웠거나, 계약에 새 경로가 붙었거나."""
    still_missing = _contract_paths() - _served_paths()
    expected = {_shape(method, path) for method, path in MISSING}
    assert still_missing == expected, (
        f"구현했는데 MISSING 에 남아 있음: {sorted(expected - still_missing)} / "
        f"계약에 새로 생겼거나 빠뜨림: {sorted(still_missing - expected)}"
    )
