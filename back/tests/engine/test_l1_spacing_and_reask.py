"""STT 띄어쓰기에 둔감한 L1 과, L3 를 기다리는 항목도 되물음 대상으로 보는 L2.

둘 다 2026-09-04 loan-b 실물 E2E 에서 나온 것이다. Qwen 이 B02 를 "DSL 총 부채 원리금
상환 비율" 로 내자 L1 패턴이 띄어쓰기에 막혔고, L2 는 후보로 올렸지만 L3 met 이
B03 되물음보다 0.2초 늦어 재진술 카드가 빠졌다.
"""

from __future__ import annotations

from contracts.engine_contract import Utterance
from engine.pack.compiler import compile_pack
from engine.pack.loader import load_pack
from engine.tiers.l1 import matcher
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakePackSource
from tests.engine.test_l2_hybrid import _lexical_only_engine


def test_l1_keyword_matches_when_stt_splits_the_compound_word(pack_json):
    pack = load_pack(FakePackSource(pack_json), PACK_VERSION)
    compiled = compile_pack(pack_json, pack)
    hits = matcher.match(
        "중도 해지 이율은 약정 이율에 차감률을 곱해서 계산됩니다",
        pack,
        compiled,
        frozenset({"required"}),
    )
    hit = next(h for h in hits if h.item.code == "DEP-INT-002")
    # "중도해지이율" 키워드는 띄어 전사된 채로도 '적용 이율' 요소를 채워야 한다
    assert "적용 이율" in hit.elements


def test_reask_targets_the_item_the_teller_just_covered_even_before_l3_settles(pack_json):
    engine = _lexical_only_engine(pack_json)
    pack = engine.load_pack(PACK_VERSION)
    state = engine.initial_state("S", pack, "text")

    # 돌려 말한 은행원 발화: L1 은 빗나가고 L2 후보(needs_refine)로만 올라간다
    teller = Utterance("U-1", "teller", "만기 전에 깨시면 약정이율보다 낮은 이율이 적용됩니다.", 1)
    r1 = engine.judge(teller, pack, state)
    assert r1.needs_refine and not r1.verdicts
    state = engine.apply(engine.observe(state, teller), r1)

    # L3 가 아직 답하기 전에 고객이 되묻는다 — 카드는 그래도 떠야 한다
    r2 = engine.judge(Utterance("U-2", "customer", "네? 그게 무슨 말이에요?", 2), pack, state)
    assert [a.assist_type for a in r2.assists] == ["rephrase"]
    assert r2.assists[0].item_code == "DEP-INT-002"
    assert r2.assists[0].source_utterance_ref == "U-1"
