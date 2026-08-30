"""실물 LLM 으로 judge_cases 의 L3 케이스를 돌린다. 모델 선택 실측용 (DESIGN D4).

back/.env 의 APP_LLM_PROVIDER · APP_LLM_API_KEY · APP_LLM_MODEL 이 있을 때만 돈다. 없으면 skip.
L2 는 fake 임베더 그대로 (후보 선별은 같고 L3 판정만 실물). -s 로 실행하면 모델 응답을 찍는다.
예산은 판정 품질을 보기 위해 30초로 연다. 실제 소요 시간은 출력의 l3 ms 로 본다.

    uv run pytest tests/engine/test_live_llm.py -s
"""

from __future__ import annotations

import pytest

from engine.adapters.cache.memory import MemoryDecisionCache
from engine.adapters.vector_index.memory import MemoryVectorIndex
from engine.build import build_engine
from server.bootstrap.settings import Settings
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakeChunkIndex, FakeEmbedder, FakePackSource
from tests.engine.test_judge_cases import CASES, PHRASES, _run

settings = Settings()
pytestmark = pytest.mark.skipif(
    not settings.llm_model, reason="APP_LLM_MODEL 없음 → 실물 LLM 테스트 생략"
)
L3_CASES = [c for c in CASES if "utterance" in c and c["expect"]["tier"] == "L3"]


@pytest.fixture(scope="module")
def engine(pack_json):
    from engine.adapters.llm.litellm import LiteLlmJudge

    codes = [it["code"] for it in pack_json["items"]]
    embedder = FakeEmbedder(codes, PHRASES)
    return build_engine(
        FakePackSource(pack_json),
        embedder,
        MemoryVectorIndex(),
        FakeChunkIndex([], embedder),
        LiteLlmJudge(
            settings.llm_model, provider=settings.llm_provider, api_key=settings.llm_api_key
        ),
        MemoryDecisionCache(),
        l3_budget_ms=30_000,
    )


@pytest.mark.parametrize("case", L3_CASES, ids=lambda c: c["name"])
def test_live_l3(engine, case):
    pack = engine.load_pack(PACK_VERSION)
    results, _state, _ = _run(engine, pack, case)
    assert len(results) == 2, "needs_refine 가 켜지지 않아 L3 가 불리지 않음"
    second = results[1]
    got_full = [(v.item_code, v.axis, v.state, v.missing_elements) for v in second.verdicts]
    model = f"{settings.llm_provider}/{settings.llm_model}"
    print(
        f"\n[{model}] {case['name']}: l3 {second.trace.l3_ms:.0f}ms "
        f"tokens={second.trace.llm_tokens}\n  실제: {got_full}"
    )
    assert second.trace.l3_called, "L3 호출 실패(LlmUnavailable) 또는 예산 초과 → 잠정 판정 유지됨"
    got = {(v.item_code, v.axis, v.state) for v in second.verdicts}
    for ev in case["expect"]["verdicts"]:
        if ev.get("decided_by", "L3") != "L3":
            continue
        assert (ev["item_code"], ev["axis"], ev["state"]) in got, f"기대 {ev} 실제 {got}"
        if "missing_elements" in ev:
            v = next(x for x in second.verdicts if x.item_code == ev["item_code"])
            assert set(v.missing_elements) == set(ev["missing_elements"]), (
                f"missing_elements 기대 {ev['missing_elements']} 실제 {v.missing_elements}"
            )
