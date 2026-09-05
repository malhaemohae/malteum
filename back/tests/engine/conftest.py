import json
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
PACK_VERSION = "DEP-2026.08-v6"


@pytest.fixture(scope="session")
def pack_json() -> dict:
    return json.loads((FIX / f"rulepack_{PACK_VERSION}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def scenario_a() -> list[dict]:
    return json.loads((FIX / "events_scenario_a.json").read_text(encoding="utf-8"))
