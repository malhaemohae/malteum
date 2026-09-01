"""L2 하이브리드(자모 trigram 덮임 + dense 융합). 임베딩 없이도 문자 신호만으로 걸러진다."""

from __future__ import annotations

import pytest

from engine.adapters.cache.memory import MemoryDecisionCache
from engine.adapters.vector_index.memory import MemoryVectorIndex
from engine.build import build_engine
from engine.pack.compiler import compile_pack
from engine.pack.loader import load_pack
from engine.tiers.l2 import lexical
from engine.tiers.l2.searcher import fused_scores
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakeChunkIndex, FakeEmbedder, FakePackSource, ScriptedLlmJudge


@pytest.fixture(scope="module")
def compiled(pack_json):
    pack = load_pack(FakePackSource(pack_json), PACK_VERSION)
    return pack, compile_pack(pack_json, pack)


def test_coverage_separates_relevant_from_unrelated(compiled):
    _, cp = compiled
    hit = lexical.coverage("네? 중간에 깨면 그것밖에 못 받아요?", cp.tri)
    assert max(hit, key=hit.get) == "DEP-INT-002" and hit["DEP-INT-002"] >= 0.5
    for text in ("여기 주차장 있어요?", "네, 잠시만 기다려 주세요."):
        assert all(v == 0.0 for v in lexical.coverage(text, cp.tri).values()), text


def test_flat_dense_is_ignored(compiled):
    """e5 류가 전 항목에 0.8 안팎을 줄 때 dense 는 무시되고 trigram 만 남는다."""
    pack, cp = compiled

    class FlatEmbedder:
        dim = 384

        def encode(self, texts):
            return [[1.0] + [0.0] * 383 for _ in texts]

    class FlatIndex:
        def search(self, pack_version, vector, top_k):
            return [(it.code, 0.8) for it in pack.items if it.type != "reference"]

    scores = dict(fused_scores("여기 주차장 있어요?", pack, cp, FlatEmbedder(), FlatIndex()))
    assert all(v == 0.0 for v in scores.values())


def test_single_spike_dense_is_kept(compiled):
    pack, cp = compiled

    class SpikeIndex:
        def search(self, pack_version, vector, top_k):
            return [("DEP-BAN-001", 0.9)]

    class ZeroEmbedder:
        dim = 384

        def encode(self, texts):
            return [[0.0] * 384 for _ in texts]

    scores = dict(fused_scores("아무 발화", pack, cp, ZeroEmbedder(), SpikeIndex()))
    assert scores["DEP-BAN-001"] == 0.9


def _lexical_only_engine(pack_json):
    codes = [it["code"] for it in pack_json["items"]]
    embedder = FakeEmbedder(codes)  # 문구 표 없음 → dense 는 항상 0. trigram 만 남는다
    return build_engine(
        FakePackSource(pack_json),
        embedder,
        MemoryVectorIndex(),
        FakeChunkIndex([], embedder),
        ScriptedLlmJudge(),
        MemoryDecisionCache(),
    )


def test_answer_by_trigram_only(pack_json):
    engine = _lexical_only_engine(pack_json)
    pack = engine.load_pack(PACK_VERSION)
    state = engine.initial_state("S", pack, "text")
    a = engine.answer("중간에 깨면 이자가 어떻게 되나요?", pack, state)
    assert a is not None and a.item_code == "DEP-INT-002"
    assert engine.answer("여기 주차장 있어요?", pack, state) is None
    assert engine.answer("점심시간에도 하나요?", pack, state) is None


def test_required_candidate_by_trigram_only(pack_json):
    engine = _lexical_only_engine(pack_json)
    pack = engine.load_pack(PACK_VERSION)
    state = engine.initial_state("S", pack, "text")
    from contracts.engine_contract import Utterance

    r = engine.judge(
        Utterance("U-1", "teller", "만기 전에 깨시면 약정이율보다 낮은 이율이 적용됩니다.", 1),
        pack,
        state,
    )
    assert r.needs_refine, "돌려 말한 필수 항목 발화가 L2 후보로 올라야 한다"
