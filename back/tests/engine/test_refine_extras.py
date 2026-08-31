"""refine 부가 경로: 교정(Corrector) 반영 · recorder 녹화/재생 · assist Generator guard."""

from __future__ import annotations

import asyncio
import json

from contracts.engine_contract import JudgeDecision, Utterance, VerdictPayload
from engine.adapters.cache.memory import MemoryDecisionCache
from engine.adapters.llm.recorder import RecordingLlmJudge, ReplayLlmJudge
from engine.adapters.vector_index.memory import MemoryVectorIndex
from engine.build import build_engine
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakeChunkIndex, FakeEmbedder, FakePackSource, ScriptedLlmJudge
from tests.engine.test_judge_cases import PHRASES

UTT = Utterance("U-1", "teller", "중도해지하시면 이자가 좀 줄어듭니다.", 1000)
SCRIPT = {
    "중도해지": JudgeDecision(
        verdicts=(
            VerdictPayload(
                "DEP-INT-002",
                "omission",
                "partial",
                "L3",
                missing_elements=("적용 이율", "차감률 또는 산출식"),
            ),
        )
    )
}


def _engine(pack_json, llm, corrector=None, generator=None):
    codes = [it["code"] for it in pack_json["items"]]
    embedder = FakeEmbedder(codes, PHRASES)
    return build_engine(
        FakePackSource(pack_json),
        embedder,
        MemoryVectorIndex(),
        FakeChunkIndex([], embedder),
        llm,
        MemoryDecisionCache(),
        corrector=corrector,
        generator=generator,
    )


class PickAllCorrector:
    def __init__(self):
        self.calls = []

    def correct(self, text, candidates):
        self.calls.append((text, candidates))
        # 허용 밖 짝 하나를 섞어도 correct 노드가 걸러야 한다
        return [(w, t) for w, t, _ in candidates] + [("없는어절", "차감률")]


def test_corrector_applies_only_allowed_pairs(pack_json):
    llm = ScriptedLlmJudge(SCRIPT)
    corrector = PickAllCorrector()
    engine = _engine(pack_json, llm, corrector=corrector)
    pack = engine.load_pack(PACK_VERSION)
    state = engine.initial_state("S", pack, "text")
    # "차감눌" 은 L0 이 확신 못하는 애매한 오전사 → 교정 후보로 올라간다
    utt = Utterance("U-2", "teller", "중도해지하면 차감눌 적용이 어떻게 되나요.", 1000)
    asyncio.run(engine.refine(utt, pack, state))
    assert corrector.calls, "교정 후보가 없어 corrector 가 불리지 않음"
    prompt = llm.prompts[-1]
    assert "차감률" in prompt.utterance_text and "차감눌" not in prompt.utterance_text
    assert "없는어절" not in prompt.utterance_text


def test_recorder_roundtrip(pack_json, tmp_path):
    tape = tmp_path / "l3.jsonl"
    real = _engine(pack_json, RecordingLlmJudge(ScriptedLlmJudge(SCRIPT), tape))
    pack = real.load_pack(PACK_VERSION)
    state = real.initial_state("S", pack, "text")
    first = asyncio.run(real.refine(UTT, pack, state))
    assert first.verdicts and tape.exists() and len(tape.read_text().splitlines()) == 1

    replay = _engine(pack_json, ReplayLlmJudge(tape))
    pack2 = replay.load_pack(PACK_VERSION)
    second = asyncio.run(replay.refine(UTT, pack2, state))
    assert second.verdicts == first.verdicts

    # 녹화에 없는 발화는 잠정 판정 유지 (빈 결과)
    other = Utterance("U-3", "teller", "지금 해지 안 하고 두시면 무조건 이득이에요.", 2000)
    missed = asyncio.run(replay.refine(other, pack2, state))
    assert missed.verdicts == ()


class EchoGenerator:
    def __init__(self, text):
        self.text = text

    def generate(self, question, evidence_texts):
        return self.text


def test_generator_guarded_by_p4(pack_json):
    pack_item = next(i for i in pack_json["items"] if i["code"] == "DEP-INT-002")
    grounded = pack_item["plain_language"][1]  # 근거 안 문장
    engine = _engine(pack_json, ScriptedLlmJudge(), generator=EchoGenerator(grounded))
    pack = engine.load_pack(PACK_VERSION)
    state = engine.initial_state("S", pack, "text")
    a = engine.answer("중간에 깨면 이자가 어떻게 되나요?", pack, state)
    assert a is not None and a.text == grounded

    fabricated = "중도해지하셔도 이자는 연 5.00% 그대로 드립니다."  # 근거 밖 숫자
    engine2 = _engine(pack_json, ScriptedLlmJudge(), generator=EchoGenerator(fabricated))
    pack2 = engine2.load_pack(PACK_VERSION)
    assert engine2.answer("중간에 깨면 이자가 어떻게 되나요?", pack2, state) is None


def test_corrector_adapter_parses_tool_call(monkeypatch):
    from types import SimpleNamespace

    from engine.adapters.llm import litellm as adapter

    def fake_completion(**kw):
        args = json.dumps({"corrections": [{"word": "차감눌", "term": "차감률"}]})
        call = SimpleNamespace(function=SimpleNamespace(name="propose", arguments=args))
        msg = SimpleNamespace(content=None, tool_calls=[call])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setattr(adapter.litellm, "completion", fake_completion)
    c = adapter.LiteLlmCorrector("x", provider="openrouter")
    assert c.correct("…", [("차감눌", "차감률", 0.5)]) == [("차감눌", "차감률")]

    def boom(**kw):
        raise ConnectionError("down")

    monkeypatch.setattr(adapter.litellm, "completion", boom)
    assert c.correct("…", [("차감눌", "차감률", 0.5)]) == []
