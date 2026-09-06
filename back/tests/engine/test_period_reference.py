"""현재 D15 전사의 기간 기산점과 동일 근거 안의 복수 수치 회귀."""

from dataclasses import replace

import pytest

from contracts.engine_contract import Evidence, NumericFact
from engine.build import build_engine
from engine.pack.compiler import NumericRef
from engine.tiers.l1.numeric import _reference
from tests.engine.fakes import FakePackSource
from tests.engine.test_numeric_context import TAX_CONTEXT, _judge


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "가입 후에 설명이 잘못됐다고 판단되시면 위법 계약 해지를 요구하실 수 있고 "
            "계약서류를 받은 날부터 3년 안에 하셔야 합니다.",
            [("3년", "5년")],
        ),
        ("계약서류를 받은 날로부터 3년 안에 위법계약 해지를 요구할 수 있습니다.", [("3년", "5년")]),
        ("위법사실을 안 날부터 2년 이내입니다.", [("2년", "1년")]),
        ("위법 사실을 안 날로부터 5년 이내입니다.", [("5년", "1년")]),
        ("계약서류를 받은 날부터 5년, 위법사실을 안 날부터 1년 이내입니다.", []),
        (
            "계약서류를 받은 날부터 3년, 위법사실을 안 날부터 2년 이내입니다.",
            [("3년", "5년"), ("2년", "1년")],
        ),
        ("위법계약 해지 기간은 3년입니다.", []),
        ("계약서류를 받은 날부터 또는 위법사실을 안 날부터 3년입니다.", []),
        ("주차권을 받은 날부터 3년입니다.", []),
    ],
)
def test_period_is_bound_to_the_named_start_date(pack_json, text, expected):
    alerts = _judge(build_engine(FakePackSource(pack_json)), text)
    assert [(a.comparison.said, a.comparison.reference) for a in alerts] == expected
    assert all(a.item_code == "DEP-TER-001" and a.evidence is not None for a in alerts)


def test_split_period_keeps_the_start_date(pack_json):
    previous = replace(TAX_CONTEXT, text="위법계약 해지는 계약서류를 받은 날부터입니다.")
    alerts = _judge(build_engine(FakePackSource(pack_json)), "3년입니다.", previous=(previous,))
    assert [(a.comparison.said, a.comparison.reference) for a in alerts] == [("3년", "5년")]


@pytest.mark.parametrize("span", ["5년, 위법사실을 안 날부터 1년 이내", "5년만 기재", "11년"])
def test_reference_never_displays_a_different_fact_value(span):
    ref = NumericRef(NumericFact("기간", "1", "년"), Evidence("doc", 1, span))
    assert _reference(ref) == "1년"
