"""현재 C13 전사와 복합 금리 문장의 숫자 귀속 회귀."""

import json

import pytest

from engine.build import build_engine
from tests.engine.conftest import FIX
from tests.engine.fakes import FakePackSource
from tests.engine.test_numeric_context import _judge


@pytest.mark.parametrize(
    "text, said",
    [
        (
            "연체하시면 대출이자율에 연체가산이자율 연 5%가 더해진 연체이자율이 적용됩니다.",
            "5%",
        ),
        (
            "연체하시면 대출이자율에 연체가산이자율 연 3%가 더해진 연체이자율이 적용됩니다.",
            None,
        ),
        ("대출이자율에 연체 가산 이자율 연 사 퍼센트가 더해집니다.", "4%"),
        ("대출이자율과 연체가산이자율은 5%입니다.", None),
        ("대출이자율 및 연체가산이자율은 5%입니다.", None),
        ("대출이자율은 연체가산이자율과 달리 5%입니다.", None),
        ("연체가산이자율에 대출이자율 연 5%가 더해집니다.", None),
        ("대출이자율은 5%, 연체가산이자율은 3%입니다.", None),
        ("대출이자율은 5%, 연체가산이자율은 4%입니다.", "4%"),
    ],
)
def test_compound_rate_binds_only_an_explicit_addend(text, said):
    raw = json.loads((FIX / "rulepack_LOAN-2026.08-v7.json").read_text(encoding="utf-8"))
    engine = build_engine(FakePackSource(raw))
    alerts = _judge(engine, text, version=raw["pack_version"])
    assert [a.comparison.said for a in alerts] == ([said] if said else [])
    if said:
        assert alerts[0].item_code == "LOAN-ARR-001"
        assert alerts[0].comparison.reference == "연 3%"
        assert alerts[0].evidence is not None
