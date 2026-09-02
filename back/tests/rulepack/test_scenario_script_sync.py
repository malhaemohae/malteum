"""시연 대본(`assets/scenarios/*/script.json`)과 그 파생물이 같은 상담을 말하는지 본다.

대본은 TTS 음원·계약 fixture(`events_scenario_a.json`)·기대 판정의 진실 원천이다. 이벤트
fixture 는 `scripts/gen_scenario_trace.py` 로 대본에서 만들지만, 누가 어느 한쪽만 고치면
심사위원이 듣는 음성과 테스트가 검증하는 상담이 갈라진다. 2026-09-03 까지 실제로 그 상태였다
(이벤트는 초안 대사, 대본은 확정 대사). 여기서 발화 순서·화자·문장, 팩 버전, 종료 요약을 대조한다.
엔진을 돌리지 않으므로 빠르다. 판정 내용의 정합은 `validate.py` 와 엔진 접기 테스트가 본다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.services.stt.assembler import utterances as split_sentences

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = REPO_ROOT / "assets" / "scenarios"
FIXTURES = REPO_ROOT / "back" / "contracts" / "fixtures"

# 대본 → 그 대본에서 생성한 이벤트 fixture. 대출은 아직 trace fixture 가 없다
TRACES = {"preset-dep-a": "events_scenario_a.json"}


def _scripts() -> dict[str, dict]:
    return {
        p.parent.name: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(SCENARIOS.glob("*/script.json"))
    }


@pytest.fixture(scope="module")
def scripts() -> dict[str, dict]:
    return _scripts()


def test_every_script_pack_is_a_fixture_pack(scripts) -> None:
    """대본이 가리키는 팩이 fixtures 에 없으면 시연 서버가 그 세션을 못 연다."""
    for preset, script in scripts.items():
        path = FIXTURES / f"rulepack_{script['pack_version']}.json"
        assert path.exists(), f"{preset}: {script['pack_version']} 팩 파일이 fixtures 에 없다"
        pack = json.loads(path.read_text(encoding="utf-8"))
        assert pack["product"]["code"] == script["product_code"], preset


def test_expected_summary_counts_required_items(scripts) -> None:
    """대본의 기대 요약이 팩의 필수 항목 수·코드와 맞아야 한다."""
    for preset, script in scripts.items():
        pack = json.loads(
            (FIXTURES / f"rulepack_{script['pack_version']}.json").read_text(encoding="utf-8")
        )
        required = {it["code"] for it in pack["items"] if it["type"] == "required"}
        summary = script["expected_summary"]
        assert summary["items_total"] == len(required), preset
        listed = set(summary["met_codes"]) | set(summary.get("partial_codes", []))
        listed |= set(summary["unmet_codes"])
        assert listed == required, (
            f"{preset}: 요약의 항목 집합 {sorted(listed)} != 팩 {sorted(required)}"
        )
        assert summary["met"] + summary["partial"] + summary["unmet"] == len(required), preset


@pytest.mark.parametrize("preset", sorted(TRACES))
def test_trace_fixture_was_generated_from_script(scripts, preset) -> None:
    script = scripts[preset]
    events = json.loads((FIXTURES / TRACES[preset]).read_text(encoding="utf-8"))
    said = [
        (e["utterance"]["speaker"], e["utterance"]["text"])
        for e in events
        if e["kind"] == "utterance"
    ]
    expected = [
        (line["speaker"], sentence)
        for line in script["lines"]
        for sentence in split_sentences(line["text"])
    ]
    assert said == expected, (
        "이벤트 fixture 의 발화가 대본과 다르다. gen_scenario_trace.py 로 다시 만든다"
    )

    started = next(e for e in events if e["kind"] == "session_started")
    assert started["pack_version"] == script["pack_version"]
    assert started["session_started"]["preset_id"] == preset
    ended = next(e for e in events if e["kind"] == "session_ended")
    summary = ended["session_ended"]["summary"]
    keys = ("items_total", "met", "partial", "unmet", "violations", "alerts", "assists_adopted")
    for key in keys:
        assert summary[key] == script["expected_summary"][key], key
