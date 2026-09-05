"""화자 단계 (`services/stt/diarization.py` · `speaker.py` · `session.py`).

시연 음성이 mono 단일 파일이라 채널로 못 가른다. 화자 분리가 준 **번호**를 발화에
붙이고 그 번호를 `teller`·`customer` 로 옮기는 것이 서버 몫이다.

**틀리면 조용히 틀린다.** 엔진 게이트가 화자로 판정 축을 가르기 때문에(teller →
필수 고지·금지 발언 / customer → 위험 신호·되물음), 화자가 뒤집히면 경보가 안 뜨거나
고지가 미고지로 남는다. 화면에는 아무 오류도 안 나온다. 그래서 대본의 `speaker` 열을
정답지로 삼고, Sortformer 가 시연 음원을 실제로 훑어 낸 구간
(`tests/fixtures/sortformer_scenarios.json`)으로 재생해 대조한다.

실물 LLM 도 실물 사이드카도 부르지 않는다(`test_no_live_adapters.py`). `RoleJudge`
자리에는 대본의 정답을 모르는 가짜를 세우고 — 발화에 안내·설명 어휘가 있으면 teller
라고만 답한다 — 사이드카 자리에는 가짜 WebSocket 을 세운다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from engine.adapters.pack_source.file import FilePackSource
from engine.build import build_engine
from engine.tiers.l1.gate import SPEAKER_CONFIDENCE_THRESHOLD, gate
from server.bootstrap.settings import Settings
from server.services.stt.base import Transcript
from server.services.stt.diarization import (
    ScriptedDiarization,
    SortformerDiarization,
    SpeakerSegment,
    TranscriptDiarization,
)
from server.services.stt.session import SttSession
from server.services.stt.speaker import (
    MAX_ASKS,
    MIN_FIRST_CHARS,
    NO_DIARIZATION_CONFIDENCE,
    PROVISIONAL_CONFIDENCE,
    SPEAKER_HOLD_MS,
    RoleMapper,
    RoleRequest,
    RoleVerdict,
    SpeakerResolver,
)

BACK = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (BACK / "tests" / "fixtures" / "sortformer_scenarios.json").read_text(encoding="utf-8")
)
SCENARIOS = BACK.parent / "assets" / "scenarios"
PACK_VERSION = "DEP-2026.08-v6"

# 대본에서 은행원이 쓰는 안내·설명 어휘. 가짜 심판이 이것만 보고 답한다
TELLER_MARKS = ("안내", "적용", "계산", "심사")


class _Clock:
    """SttSession 이 세션에서 쓰는 것은 시계 하나뿐이다."""

    def __init__(self) -> None:
        self.now_ms = 0

    def elapsed_ms(self) -> int:
        return self.now_ms


class _MarkerJudge:
    """대본의 정답을 모르는 가짜 심판. 안내·설명 어휘가 있으면 은행원이라고 답한다."""

    def __init__(self, confidence: float = 0.9) -> None:
        self.confidence = confidence
        self.requests: list[RoleRequest] = []

    async def decide(self, request: RoleRequest) -> RoleVerdict:
        self.requests.append(request)
        text = " ".join(request.recent)
        if any(mark in text for mark in TELLER_MARKS):
            return RoleVerdict("teller", self.confidence, "안내·설명 어휘")
        return RoleVerdict("customer", self.confidence, "안내·설명 어휘 없음")


def _script(preset: str) -> dict:
    return json.loads((SCENARIOS / preset / "script.json").read_text(encoding="utf-8"))


def _replay(preset: str, judge, *, segments: list[str] | None = None, hold_ms: int | None = None):
    """대본 한 편을 STT 경로로 흘린다. 줄 하나가 확정 전사 하나다.

    화자 분리 구간은 그 줄이 끝난 시각까지만 보인다 — 실제 스트림에서 아직 오지 않은
    구간을 미리 보고 화자를 맞히면 재생 결과가 실제보다 좋게 나온다.

    줄마다 붙잡기(DEC-7)와 배경 추론이 끝나기를 기다린 뒤 다음 줄로 넘어간다. 실제
    스트림에서도 한 발화가 방출되기 전에 다음 확정 전사가 오는 일은 드물고, 그렇게
    겹치는 경우의 순서 유지는 아래 `test_a_slow_answer...` 가 따로 본다.
    """
    script = _script(preset)
    durations = FIXTURE["presets"][preset]["line_duration_ms"]
    clock = _Clock()
    source = ScriptedDiarization.from_lines(
        segments if segments is not None else FIXTURE["presets"][preset]["segments"],
        now_ms=lambda: clock.now_ms,
    )
    resolver = SpeakerResolver(source, RoleMapper(judge))
    submitted: list = []

    async def submit(utterance):
        submitted.append(utterance)

    async def publish(message):
        pass

    stt = SttSession(
        clock,
        publish,
        submit,
        resolver,
        hold_ms=SPEAKER_HOLD_MS if hold_ms is None else hold_ms,
    )

    async def run():
        by_line = []
        for line in script["lines"]:
            duration = durations[line["id"]]
            clock.now_ms = line["start_ms"] + duration
            before = len(submitted)
            await stt._on_transcript(
                Transcript(
                    text=line["text"],
                    final=True,
                    start_ms=line["start_ms"],
                    duration_ms=duration,
                )
            )
            await stt._releasing  # 붙잡아 둔 발화가 다 나갈 때까지
            by_line.append((line, duration, submitted[before:]))
        await stt.aclose()
        return by_line

    return resolver, asyncio.run(run())


# --- (a) 시연 대본 재생 --------------------------------------------------------


def test_the_demo_scripts_get_every_line_from_the_sortformer_segments():
    """32줄 전부. 대본 두 편(16줄씩)을 Sortformer 실측 구간으로 재생한다.

    지표를 **두 개**로 나눠 센다. 값이 같아 보여도 재는 것이 다르다.

    1. **재생이 끝난 뒤(`final`)**: 줄마다 고른 화자 번호를, 재생이 끝난 시점의
       역할표에 넣은 값. 화자 접착과 역할표가 결국 맞았는지를 본다.
    2. **흘러나간 시점(`streaming`)**: 그 줄이 실제로 방출될 때 실린 `speaker`.
       은행원이 화면에서 보는 값이자 게이트가 받는 값이라 이쪽이 제품의 지표다.

    붙잡기(DEC-7)가 들어오기 전에는 각 상담의 첫 줄이 잠정 라벨로 나가 streaming 이
    30/32 였다. 이제 새 번호의 첫 발화도 역할이 확정될 때까지 붙잡으므로 둘 다 32/32 다.

    첫 판정 규칙이 글자 수 기준이 된 뒤로도(DEC-8) 둘 다 32/32 다. 새 번호가 처음 내는
    줄이 한 문장뿐인 B02 도 그 문장이 길어 곧바로 판정이 걸리고, 나머지 세 줄(A01 3문장 ·
    A02 2문장 · B01 2문장)은 문장이 둘 이상이라 역시 그 줄 안에서 판정이 걸린다.
    """
    final_hits = streaming_hits = lines_total = 0
    provisional: list[str] = []
    wrong: list[str] = []

    for preset in ("preset-dep-a", "preset-loan-b"):
        resolver, replayed = _replay(preset, _MarkerJudge())
        for line, duration, utterances in replayed:
            lines_total += 1
            picked = resolver.speaker_of(line["start_ms"], duration)
            assert picked is not None, f"{line['id']} 에 붙는 화자 구간이 없습니다"
            role = resolver.mapper.role_of(picked[0])
            assert role is not None, f"{line['id']} 의 번호 {picked[0]} 이 확정되지 않았습니다"
            if role[0] == line["speaker"]:
                final_hits += 1

            assert utterances, f"{line['id']} 이 한 문장도 나가지 않았습니다"
            emitted = {u.speaker for u in utterances}
            if emitted == {line["speaker"]}:
                streaming_hits += 1
            else:
                wrong.append(f"{line['id']} {line['speaker']} → {sorted(emitted)}")
            if any(
                u.speaker_confidence is not None and u.speaker_confidence <= PROVISIONAL_CONFIDENCE
                for u in utterances
            ):
                provisional.append(line["id"])

    # 재생 결과를 눈으로 확인할 수 있게 한 줄 남긴다 (`pytest -s` 로 보인다)
    print(
        f"\n화자 final {final_hits}/{lines_total} · streaming {streaming_hits}/{lines_total}"
        f" · 잠정으로 나간 줄 {provisional or '없음'}"
        f" · 라벨이 뒤집힌 줄 {wrong or '없음'}"
    )
    assert lines_total == 32
    assert final_hits == 32, f"재생 종료 시점 화자 {final_hits}/32"
    assert streaming_hits == 32, f"흘러나간 시점 화자 {streaming_hits}/32 — 뒤집힌 줄 {wrong}"
    assert not provisional, f"붙잡기가 있는데 잠정으로 나간 줄: {provisional}"


def test_the_first_teller_line_of_each_script_goes_out_with_a_settled_label():
    """DEC-7·DEC-8 이 함께 지키는 자리. A02·B02 는 각 상담에서 은행원 번호가 처음 나오는 줄이다.

    두 줄 모두 필수 고지를 담는다(A02 는 `DEP-INT-001`, B02 는 `LOAN-DSR-001`). 잠정
    라벨로 나가면 신뢰도가 게이트 아래라 그 판정이 통째로 접힌다.

    **B02 는 한 문장뿐이다.** 첫 판정에 발화 두 개를 요구하면 이 줄은 상한까지 아무것도
    묻지 못해 접힌다. 글자 수 기준(`MIN_FIRST_CHARS`)이라야 긴 한 문장을 그 자리에서
    묻고 확정한다 — 규칙을 발화 수에서 글자 수로 바꾼 이유가 이 줄이다.
    """
    for preset, first_teller in (("preset-dep-a", "A02"), ("preset-loan-b", "B02")):
        _, replayed = _replay(preset, _MarkerJudge())
        emitted = {line["id"]: us for line, _, us in replayed}[first_teller]
        assert [u.speaker for u in emitted] == ["teller"] * len(emitted)
        assert all(u.speaker_confidence >= SPEAKER_CONFIDENCE_THRESHOLD for u in emitted), (
            f"{first_teller} 가 게이트 아래 신뢰도로 나갔습니다"
        )
        assert all(gate(u).types == frozenset({"required", "forbidden"}) for u in emitted)


# --- (b) 셋째 번호 ------------------------------------------------------------


def test_a_third_number_is_absorbed_into_the_role_it_speaks_like():
    """화자 분리는 같은 사람을 두 번호로 가르기도 한다. 셋째 번호라고 버리지 않는다.

    같은 고객의 구간(A07·A09)을 speaker_2 로 바꿔도, 그 번호의 발화를 읽은 심판이
    고객으로 돌려주면 역할표가 그대로 흡수해야 한다. 첫 화자 규칙이었다면 셋째 번호는
    역할이 없어 그 줄의 되물음·위험 신호가 통째로 빠진다.

    A07 은 이 번호의 첫 줄이고 한 문장이지만 그 문장이 길어(`MIN_FIRST_CHARS` 이상)
    그 자리에서 판정이 걸린다(DEC-8). 그래서 첫 줄부터 정식 고객 라벨을 받는다.
    """
    segments = [
        s.replace("speaker_0", "speaker_2") if s.startswith(("55.600", "71.280")) else s
        for s in FIXTURE["presets"]["preset-dep-a"]["segments"]
    ]
    resolver, replayed = _replay("preset-dep-a", _MarkerJudge(), segments=segments)
    emitted = {line["id"]: us for line, _, us in replayed}

    assert resolver.mapper.role_of("speaker_2") == ("customer", 0.9)
    assert {u.speaker for u in emitted["A07"]} == {"customer"}
    assert {u.speaker for u in emitted["A09"]} == {"customer"}


# --- (c) 확정 전 · 확정 후 -----------------------------------------------------


def test_an_utterance_waits_for_the_role_but_only_up_to_the_limit():
    """DEC-7. 확정되면 정식 라벨로, 상한을 넘기면 잠정 라벨로 나간다."""
    answered = asyncio.Event()

    class _SlowJudge:
        async def decide(self, request: RoleRequest) -> RoleVerdict:
            await answered.wait()
            return RoleVerdict("customer", 0.9, "느린 심판")

    source = ScriptedDiarization([SpeakerSegment(0, 20_000, "speaker_0")])
    resolver = SpeakerResolver(source, RoleMapper(_SlowJudge()))

    async def run():
        # 긴 한 문장이라 붙잡기 전에 판정이 걸린다(DEC-8). 짧은 인사말이면 상한에 닿아야
        # 물으므로 붙잡는 동안 답이 올 수 없다
        picked = resolver.pick("작년에 넣어 둔 정기예금이 있는데요.", 0, 3_000)
        # 상한 안에 답이 오면 정식 라벨
        asyncio.get_running_loop().call_later(0.05, answered.set)
        settled = await resolver.hold(*picked, 2.0)
        # 이미 확정된 번호는 기다리지 않는다
        again = await resolver.hold(*resolver.pick("그냥 해지할게요.", 10_000, 3_000), 2.0)
        return settled, again

    settled, again = asyncio.run(run())
    assert not settled.provisional and settled.role == "customer"
    assert settled.confidence >= SPEAKER_CONFIDENCE_THRESHOLD
    assert again.role == "customer"


def test_an_utterance_gives_up_and_goes_out_provisionally_after_the_limit():
    """상한을 넘기면 붙잡기를 포기한다. 확정을 기다리며 화면이 멈추면 안 된다."""

    class _SilentJudge:
        async def decide(self, request: RoleRequest) -> RoleVerdict:
            await asyncio.Event().wait()  # 영원히 답하지 않는다
            raise AssertionError("여기까지 오지 않는다")

    clock = _Clock()
    submitted: list = []

    async def submit(utterance):
        submitted.append(utterance)

    async def publish(message):
        pass

    source = ScriptedDiarization([SpeakerSegment(0, 20_000, "speaker_0")])
    resolver = SpeakerResolver(source, RoleMapper(_SilentJudge()))
    # 상한만 짧게 줄인다. 기본값 3초를 그대로 쓰면 테스트가 3초를 그냥 기다린다
    stt = SttSession(clock, publish, submit, resolver, hold_ms=200)

    async def run():
        await stt._on_transcript(Transcript(text="안녕하세요.", final=True, start_ms=0))
        await stt._releasing
        await stt.aclose()

    asyncio.run(run())

    assert [u.speaker for u in submitted] == ["teller"]  # 근거가 없으면 미고지 쪽
    assert [u.speaker_confidence for u in submitted] == [PROVISIONAL_CONFIDENCE]
    assert Settings().speaker_hold_ms == SPEAKER_HOLD_MS == 3000
    # DEC-8: OpenRouter 왕복 2~5초 실측. 1500 이면 L3 가 필요한 판정이 통째로 빠진다
    assert Settings().l3_budget_ms == 3000


def test_a_slow_answer_does_not_let_a_later_utterance_overtake_an_earlier_one():
    """붙잡는 동안 순서가 뒤바뀌면 리포트의 시간 순서가 무너진다.

    앞 발화의 번호는 0.5초 뒤에야 확정되고 뒤 발화의 번호는 곧바로 확정된다. 큐 없이
    각자 기다리면 뒤 발화가 먼저 나간다.
    """

    class _UnevenJudge:
        async def decide(self, request: RoleRequest) -> RoleVerdict:
            if request.speaker_id == "speaker_0":
                await asyncio.sleep(0.5)
                return RoleVerdict("customer", 0.9, "느리게 온 답")
            return RoleVerdict("teller", 0.9, "곧바로 온 답")

    clock = _Clock()
    submitted: list = []

    async def submit(utterance):
        submitted.append(utterance)

    async def publish(message):
        pass

    source = ScriptedDiarization(
        [SpeakerSegment(0, 4_000, "speaker_0"), SpeakerSegment(5_000, 9_000, "speaker_1")]
    )
    resolver = SpeakerResolver(source, RoleMapper(_UnevenJudge()))
    stt = SttSession(clock, publish, submit, resolver)

    async def run():
        # 두 문장 다 길다. 짧으면 DEC-8 이 판정을 미뤄 둘 다 잠정으로 나가고, 이 테스트가
        # 재려던 라벨 차이가 사라진다
        clock.now_ms = 4_000
        await stt._on_transcript(
            Transcript(text="먼저 말한 쪽의 문장입니다.", final=True, start_ms=0, duration_ms=4_000)
        )
        clock.now_ms = 9_000
        await stt._on_transcript(
            Transcript(
                text="나중에 말한 쪽의 문장입니다.", final=True, start_ms=5_000, duration_ms=4_000
            )
        )
        await stt.aclose()

    asyncio.run(run())

    assert [u.text for u in submitted] == [
        "먼저 말한 쪽의 문장입니다.",
        "나중에 말한 쪽의 문장입니다.",
    ]
    assert [u.speaker for u in submitted] == ["customer", "teller"]
    assert all(u.speaker_confidence >= SPEAKER_CONFIDENCE_THRESHOLD for u in submitted)


# --- (d) 화자 분리 없음 --------------------------------------------------------


def _without_diarization(text: str) -> list:
    clock = _Clock()
    submitted: list = []

    async def submit(utterance):
        submitted.append(utterance)

    async def publish(message):
        pass

    stt = SttSession(clock, publish, submit)

    async def run():
        await stt._on_transcript(Transcript(text=text, final=True))
        await stt.aclose()

    asyncio.run(run())
    return submitted


def test_without_diarization_everything_stays_teller_at_the_contract_default():
    """예전 동작 그대로. 신뢰도는 **계약 기본값 None** 이고 0.0 이 아니다.

    0.0 을 실으면 게이트가 은행원 발화를 전부 접는다. 화자 분리 공급원이 없는 것은
    지금 배포되는 경로(Deepgram · replay)의 정상 상태라, 그 경로의 필수 고지·금지
    발언 판정이 통째로 사라진다.
    """
    submitted = _without_diarization("그냥 해지할게요. 딸이 알려준 계좌로 보내 주세요.")

    assert [u.speaker for u in submitted] == ["teller", "teller"]
    assert [u.speaker_confidence for u in submitted] == [NO_DIARIZATION_CONFIDENCE, None]
    assert all(gate(u).types == frozenset({"required", "forbidden"}) for u in submitted)


def test_without_diarization_l1_still_finds_the_required_disclosure():
    """A1 회귀. 화자 분리 없이 A02 를 흘리면 `DEP-INT-001` 이 met 로 나와야 한다.

    이 판정이 사라지는 것이 신뢰도 0.0 의 실제 피해였다. 게이트만이 아니라 엔진까지
    실제로 통과시켜 확인한다.
    """
    line = next(line for line in _script("preset-dep-a")["lines"] if line["id"] == "A02")
    submitted = _without_diarization(line["text"])
    engine = build_engine(FilePackSource(BACK / "contracts" / "fixtures"))
    pack = engine.load_pack(PACK_VERSION)
    state = engine.initial_state("s-a1-regression", pack, "live")

    verdicts = [v for u in submitted for v in engine.judge(u, pack, state).verdicts]
    met = {v.item_code for v in verdicts if v.state == "met"}
    assert "DEP-INT-001" in met, f"필수 고지 판정이 사라졌습니다: {verdicts}"


# --- (e) other -----------------------------------------------------------------


def test_an_outsider_is_logged_but_never_submitted():
    """상담 당사자가 아닌 소리를 은행원의 고지나 고객의 위험 신호로 기록하면 증빙이 오염된다."""

    class _OutsiderJudge:
        async def decide(self, request: RoleRequest) -> RoleVerdict:
            if request.speaker_id == "speaker_2":
                return RoleVerdict("other", 0.9, "상담 당사자가 아님")
            return RoleVerdict("teller", 0.9, "상담 당사자")

    clock = _Clock()
    submitted: list = []

    async def submit(utterance):
        submitted.append(utterance)

    async def publish(message):
        pass

    source = ScriptedDiarization([SpeakerSegment(0, 5_000, "speaker_2")])
    resolver = SpeakerResolver(source, RoleMapper(_OutsiderJudge()))
    stt = SttSession(clock, publish, submit, resolver)

    async def run():
        await stt._on_transcript(Transcript(text="지나가는 소리.", final=True, start_ms=0))
        await stt._on_transcript(Transcript(text="여기 사람 있어요.", final=True, start_ms=1_000))
        await stt.aclose()

    asyncio.run(run())

    assert resolver.mapper.role_of("speaker_2") == ("other", 0.9)
    assert submitted == []


# --- 첫 판정의 근거 (DEC-8 · DEC-9) --------------------------------------------


def test_one_long_utterance_is_enough_to_ask_and_settle_right_away():
    """긴 한 문장은 그 자체로 근거다. 둘째 발화를 기다리지 않는다.

    기다리면 그 줄이 상한까지 잠정 라벨에 머물고, loan-b B02 처럼 그 줄에 필수 고지가
    걸려 있으면 게이트가 은행원 판정을 통째로 접는다. 규칙을 발화 수에서 글자 수로 바꾼
    이유이며, 여기서는 판정기가 부르는 시점과 확정 여부를 직접 본다.
    """
    judge = _MarkerJudge()
    mapper = RoleMapper(judge)
    line = "네, 먼저 소득과 기존 대출을 확인해서 DSR 을 산출하고 심사에 활용합니다."

    async def run():
        mapper.observe("speaker_1", line)
        await mapper.pending()

    asyncio.run(run())

    assert len("".join(line.split())) >= MIN_FIRST_CHARS
    assert [len(r.recent) for r in judge.requests] == [1], "긴 한 문장인데 묻지 않았습니다"
    assert mapper.role_of("speaker_1") == ("teller", 0.9)


def test_a_short_greeting_alone_is_not_asked_until_the_next_utterance_arrives():
    """인사말 하나로는 묻지 않는다. 확정된 번호는 다시 묻지 않기 때문이다.

    dep-a E2E 실측(CTX-017)에서 판정기가 "안녕하세요." 한 문장만 보고 teller(0.9)로
    확정했고, 그 번호가 상담 내내 은행원으로 남아 위험 신호 경보와 되물음 카드가
    통째로 사라졌다. 같은 판정기도 발화 두 개를 주면 맞힌다.
    """
    judge = _MarkerJudge()
    mapper = RoleMapper(judge)

    async def run():
        mapper.observe("speaker_0", "안녕하세요.")
        await mapper.pending()
        asked_after_one = len(judge.requests)
        mapper.observe("speaker_0", "작년에 넣어 둔 정기예금이 있는데요.")
        await mapper.pending()
        return asked_after_one, len(judge.requests)

    asked_after_one, asked_after_two = asyncio.run(run())

    assert len("".join("안녕하세요.".split())) < MIN_FIRST_CHARS
    assert asked_after_one == 0, "짧은 발화 하나로 물었습니다"
    assert asked_after_two == 1
    assert len(judge.requests[0].recent) == 2
    assert mapper.role_of("speaker_0") == ("customer", 0.9)


def test_an_answer_based_on_one_short_utterance_is_never_settled():
    """DEC-9 가드. 상한 도달로 "안녕하세요." 하나를 물었다면 답이 0.9 여도 확정하지 않는다.

    프롬프트가 짧은 인사말에 낮은 신뢰도를 내라고 일러 두었지만 모델이 지키는지에
    기대지 않는다. 여기 심판은 늘 0.9 를 내는데, 그 답으로 확정되면 그 번호는 다시
    묻히지 않아 상담 내내 역할이 뒤집힌 채로 간다(CTX-017 이 실측한 결함).

    확정하지 못한 답은 `MAX_ASKS` 횟수로도 세지 않는다. 그래야 다음 발화에서 세 번의
    재추론 기회를 온전히 쓴다.
    """
    judge = _MarkerJudge()
    clock = _Clock()
    submitted: list = []

    async def submit(utterance):
        submitted.append(utterance)

    async def publish(message):
        pass

    source = ScriptedDiarization([SpeakerSegment(0, 20_000, "speaker_0")])
    mapper = RoleMapper(judge)
    resolver = SpeakerResolver(source, mapper)
    stt = SttSession(clock, publish, submit, resolver, hold_ms=200)

    async def run():
        await stt._on_transcript(Transcript(text="안녕하세요.", final=True, start_ms=0))
        await stt._releasing
        await mapper.pending()
        held_back = mapper.role_of("speaker_0"), mapper._numbers["speaker_0"].asks
        clock.now_ms = 10_000
        await stt._on_transcript(
            Transcript(text="작년에 넣어 둔 정기예금이 있는데요.", final=True, start_ms=10_000)
        )
        await stt._releasing
        await stt.aclose()
        return held_back

    role_after_greeting, asks_after_greeting = asyncio.run(run())

    # 상한에 닿았으므로 가진 하나로 물었고, 심판은 0.9 를 냈다
    assert [len(r.recent) for r in judge.requests] == [1, 2]
    assert role_after_greeting is None, "짧은 발화 하나에 근거한 답이 확정됐습니다"
    assert asks_after_greeting == 0, "확정하지 못한 답이 재추론 횟수를 깎았습니다"
    # 그 발화는 잠정 라벨로 나가고, 다음 발화에서 다시 물어 그 답으로 확정된다
    assert [u.speaker_confidence for u in submitted] == [PROVISIONAL_CONFIDENCE, 0.9]
    assert mapper.role_of("speaker_0") == ("customer", 0.9)


def test_a_short_greeting_next_to_a_settled_teller_goes_out_as_the_customer():
    """확정된 번호가 은행원 하나뿐이면, 새 번호의 짧은 인사말은 잠정으로 고객이 된다.

    창구 상담의 당사자는 보통 둘이다. 확정을 못 기다린 발화라도 반대 역할로 두는 편이,
    고객의 첫마디를 은행원 것으로 적어 위험 신호 축을 닫아 버리는 것보다 낫다.

    심판은 늘 0.9 를 내지만 DEC-9 가드가 그 답을 확정하지 않으므로, 번호는 미확정으로
    남고 발화는 잠정 라벨로 나간다.
    """
    judge = _MarkerJudge()
    clock = _Clock()
    submitted: list = []

    async def submit(utterance):
        submitted.append(utterance)

    async def publish(message):
        pass

    source = ScriptedDiarization(
        [SpeakerSegment(0, 5_000, "speaker_0"), SpeakerSegment(6_000, 9_000, "speaker_1")]
    )
    resolver = SpeakerResolver(source, RoleMapper(judge))
    stt = SttSession(clock, publish, submit, resolver, hold_ms=200)

    async def run():
        # 은행원 번호를 두 문장으로 먼저 확정시킨다
        clock.now_ms = 5_000
        await stt._on_transcript(
            Transcript(
                text="중도해지 기준으로 안내드리겠습니다. 기본이자율로 계산됩니다.",
                final=True,
                start_ms=0,
                duration_ms=5_000,
            )
        )
        await stt._releasing
        clock.now_ms = 9_000
        await stt._on_transcript(
            Transcript(text="안녕하세요.", final=True, start_ms=6_000, duration_ms=3_000)
        )
        await stt._releasing
        await stt.aclose()

    asyncio.run(run())

    assert resolver.mapper.role_of("speaker_0") == ("teller", 0.9)
    assert resolver.mapper.role_of("speaker_1") is None  # 인사말 하나로는 확정하지 않는다
    assert (submitted[-1].speaker, submitted[-1].speaker_confidence) == (
        "customer",
        PROVISIONAL_CONFIDENCE,
    )


# --- 재추론 조건 ---------------------------------------------------------------


def test_two_low_confidence_answers_in_a_row_trigger_one_wider_reinference():
    """확정한 번호는 다시 묻지 않는다. 다만 낮은 신뢰도가 두 번 이어지면 한 번 더 캔다.

    세 번째는 확정 번호들의 최근 발화를 두 배로 넓혀 묻고, 그 답을 신뢰도와 무관하게
    확정한다. 상한이 없으면 애매한 번호 하나가 발화마다 LLM 을 부른다.
    """
    answers = [
        RoleVerdict("teller", 0.4, "애매"),
        RoleVerdict("teller", 0.4, "애매"),
        RoleVerdict("customer", 0.4, "넓힌 문맥"),
    ]

    class _WobblyJudge:
        def __init__(self) -> None:
            self.seen: list[RoleRequest] = []

        async def decide(self, request: RoleRequest) -> RoleVerdict:
            self.seen.append(request)
            return answers[len(self.seen) - 1]

    judge = _WobblyJudge()
    mapper = RoleMapper(judge)

    async def run():
        for i in range(4):
            mapper.observe("speaker_1", f"{i} 번째 발화.")
            await mapper.pending()

    asyncio.run(run())

    assert len(judge.seen) == MAX_ASKS == 3, "확정된 뒤에도 물었습니다"
    assert mapper.role_of("speaker_1") == ("customer", 0.4)


def test_the_role_table_widens_the_context_only_on_the_last_ask():
    """재추론은 문맥을 넓혀서 묻는다. 같은 것을 그대로 다시 물으면 같은 답이 온다."""
    judge = _MarkerJudge(confidence=0.4)  # 늘 저신뢰 → 세 번 다 물린다
    mapper = RoleMapper(judge)

    async def run():
        for text in ("안내드리겠습니다.", "적용됩니다.", "계산됩니다.", "심사합니다."):
            mapper.observe("speaker_0", text)
            await mapper.pending()
        # 확정된 번호 하나를 옆에 두고, 다른 번호를 같은 방식으로 물린다
        for i in range(4):
            mapper.observe("speaker_1", f"{i} 번째 발화.")
            await mapper.pending()

    asyncio.run(run())

    asked = [r for r in judge.requests if r.speaker_id == "speaker_1"]
    assert len(asked) == 3
    assert all(k.speaker_id == "speaker_0" for r in asked for k in r.known)
    assert len(asked[-1].known[0].recent) > len(asked[0].known[0].recent)


def test_a_judge_that_raises_does_not_leave_the_number_stuck():
    """판정이 터져도 다음 발화에서 다시 묻는다. `asking` 이 안 풀리면 잠정 라벨에 갇힌다."""

    class _BrokenJudge:
        def __init__(self) -> None:
            self.calls = 0

        async def decide(self, request: RoleRequest) -> RoleVerdict:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("공급자 장애")
            return RoleVerdict("customer", 0.9, "두 번째는 성공")

    judge = _BrokenJudge()
    mapper = RoleMapper(judge)

    async def run():
        # 둘 다 긴 문장이라 발화마다 묻는다(DEC-8). 첫 판정이 터지고 둘째에서 다시 묻는다
        for text in ("이것은 첫 번째로 한 발화입니다.", "이것은 둘째로 한 발화입니다."):
            mapper.observe("speaker_0", text)
            await mapper.pending()

    asyncio.run(run())

    assert judge.calls == 2
    assert mapper.role_of("speaker_0") == ("customer", 0.9)


def test_closing_reclaims_a_role_inference_that_never_answers():
    """세션이 닫히면 진행 중인 추론을 거둔다. 기다리면 실물 판별기의 30초를 그대로 문다."""

    class _SilentJudge:
        async def decide(self, request: RoleRequest) -> RoleVerdict:
            await asyncio.Event().wait()
            raise AssertionError("여기까지 오지 않는다")

    mapper = RoleMapper(_SilentJudge())

    async def run():
        mapper.observe("speaker_0", "답이 오지 않는 발화.")
        await asyncio.sleep(0)  # 태스크가 실제로 시작하도록 한 번 양보한다
        await asyncio.wait_for(mapper.aclose(), 1.0)
        return mapper._tasks

    assert asyncio.run(run()) == set()


# --- 접착 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start_ms", "duration_ms", "expected"),
    [
        (1_000, 2_000, ("speaker_0", 1.0)),  # 통째로 한 화자 안에 든다
        (9_000, 2_000, ("speaker_1", 1.0)),
        (4_600, 500, ("speaker_0", 0.5)),  # 겹치는 구간이 없다 → 가장 가까운 쪽, 추정
        (3_000, 4_000, ("speaker_1", 0.517)),  # 두 화자에 반씩 걸쳤다 → 점유율만큼 내린다
    ],
)
def test_an_utterance_sticks_to_the_segment_it_overlaps_most(start_ms, duration_ms, expected):
    resolver = SpeakerResolver(
        ScriptedDiarization(
            [SpeakerSegment(0, 4_400, "speaker_0"), SpeakerSegment(5_500, 12_000, "speaker_1")]
        )
    )
    assert resolver.speaker_of(start_ms, duration_ms) == expected


def test_a_speaker_is_not_invented_for_an_utterance_far_from_every_segment():
    """거리 한계 밖이면 화자를 지어내지 않는다. 지어내면 그 말이 은행원의 고지로 기록된다."""
    resolver = SpeakerResolver(ScriptedDiarization([SpeakerSegment(0, 4_000, "speaker_0")]))
    assert resolver.speaker_of(60_000, 2_000) is None


def test_a_gap_exactly_at_the_limit_is_already_the_next_speaker():
    """대본은 화자가 바뀌는 자리에 무음을 1초 "이상" 둔다. 딱 1초 떨어진 구간은 옆 사람이다."""
    resolver = SpeakerResolver(ScriptedDiarization([SpeakerSegment(11_000, 15_000, "speaker_0")]))
    assert resolver.speaker_of(9_000, 1_000) is None  # 간격 정확히 1000ms
    assert resolver.speaker_of(9_001, 1_000) == ("speaker_0", 0.5)  # 999ms


# --- 사이드카 클라이언트 -------------------------------------------------------


class _FakeSidecar:
    """가짜 WebSocket. 오디오를 받으면 미리 정해 둔 구간 목록을 하나씩 돌려준다."""

    def __init__(self, replies: list[list[dict]], covered: list[int] | None = None) -> None:
        self.replies = list(replies)
        self.covered = list(covered or [])
        self.sent: list[bytes] = []
        self.closed = False
        self._out: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, pcm: bytes) -> None:
        self.sent.append(pcm)
        if self.replies:
            message: dict = {"segments": self.replies.pop(0)}
            if self.covered:
                message["covered_ms"] = self.covered.pop(0)
            await self._out.put(json.dumps(message))

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        return await self._out.get()


def _fake_websockets(monkeypatch, socket) -> None:
    import websockets

    async def connect(url, **kwargs):
        if socket is None:
            raise OSError("사이드카가 없습니다")
        return socket

    monkeypatch.setattr(websockets, "connect", connect)


def test_the_sidecar_client_replaces_the_segment_list_it_is_given(monkeypatch):
    """사이드카는 청크마다 **지금까지의 목록 전체**를 준다. 이어 붙이면 고쳐진 구간이 겹친다."""
    socket = _FakeSidecar(
        [
            [{"start_ms": 0, "end_ms": 900, "speaker_id": "speaker_0"}],
            [{"start_ms": 0, "end_ms": 1800, "speaker_id": "speaker_0"}],
        ],
        covered=[960, 1920],
    )
    _fake_websockets(monkeypatch, socket)
    source = SortformerDiarization("ws://사이드카/ws")

    async def run():
        await source.feed(b"\x00\x00" * 100)
        await asyncio.sleep(0)
        first = tuple(source.segments())
        await source.feed(b"\x00\x00" * 100)
        await asyncio.sleep(0)
        second = tuple(source.segments())
        await source.aclose()
        return first, second

    first, second = asyncio.run(run())
    assert first == (SpeakerSegment(0, 900, "speaker_0"),)
    assert second == (SpeakerSegment(0, 1800, "speaker_0"),)  # 두 개가 아니라 갈아 끼운다
    assert source.covered_ms == 1920  # 이 목록이 어디까지의 오디오를 보고 나왔는가
    assert len(socket.sent) == 2
    assert socket.closed


def test_the_sidecar_client_falls_back_to_the_last_segment_when_covered_ms_is_missing(monkeypatch):
    """구버전 사이드카는 `covered_ms` 를 주지 않는다. 그때는 마지막 구간의 끝을 그 지점으로 본다.

    전 값을 그대로 두면 이 시계가 0 에 멈추고, 발화 단위 어댑터가 무음을 재지 못해
    구간을 영영 닫지 못한다 — 전사가 한 줄도 나오지 않는다.
    """
    socket = _FakeSidecar(
        [
            [{"start_ms": 0, "end_ms": 900, "speaker_id": "speaker_0"}],
            [{"start_ms": 0, "end_ms": 1800, "speaker_id": "speaker_0"}],
        ]
    )  # covered 를 주지 않는다
    _fake_websockets(monkeypatch, socket)
    source = SortformerDiarization("ws://구버전사이드카/ws")

    async def run():
        await source.feed(b"\x00\x00" * 100)
        await asyncio.sleep(0)
        first = source.covered_ms
        await source.feed(b"\x00\x00" * 100)
        await asyncio.sleep(0)
        second = source.covered_ms
        await source.aclose()
        return first, second

    assert asyncio.run(run()) == (900, 1800)


def test_a_missing_sidecar_leaves_the_session_running_without_diarization(monkeypatch):
    """사이드카가 없어도 상담은 이어진다. 화자 분리 없음으로 내려앉을 뿐이다."""
    _fake_websockets(monkeypatch, None)
    source = SortformerDiarization("ws://없는곳/ws")
    clock = _Clock()
    submitted: list = []

    async def submit(utterance):
        submitted.append(utterance)

    async def publish(message):
        pass

    stt = SttSession(clock, publish, submit, diarization=source)

    async def run():
        await stt.feed(b"\x00\x00" * 100)  # 여기서 붙기를 시도했다가 실패한다
        await stt._on_transcript(Transcript(text="그냥 해지할게요.", final=True))
        await stt.aclose()

    asyncio.run(run())

    assert source.segments() == ()
    assert [(u.speaker, u.speaker_confidence) for u in submitted] == [("teller", None)]


def test_a_sidecar_that_stops_taking_audio_leaves_no_task_or_socket_behind(monkeypatch):
    """보내다 실패하면 다시 붙지 않기로 했으므로, 읽기 태스크와 소켓도 그때 거둔다.

    참조만 버리면 상담이 끝날 때까지 태스크 하나와 소켓 하나가 그대로 남는다.
    """
    socket = _FakeSidecar([])

    async def refuse(pcm: bytes) -> None:
        raise OSError("사이드카가 끊겼습니다")

    socket.send = refuse
    _fake_websockets(monkeypatch, socket)
    source = SortformerDiarization("ws://끊긴곳/ws")

    async def run():
        await source.feed(b"\x00\x00" * 100)  # 붙기는 했고 보내다 실패한다
        return socket.closed, len(asyncio.all_tasks())

    closed, tasks = asyncio.run(run())
    assert closed
    assert tasks == 1  # 지금 도는 것 하나뿐. 읽기 태스크가 남아 있지 않다


def test_a_transcript_without_a_length_still_overlaps_the_number_it_carried():
    """길이를 안 주는 공급자의 전사도 겹침으로 붙어야 한다.

    길이 0 구간을 쌓으면 어떤 발화와도 겹치지 않아 접착이 `_nearest` 로 내려가고,
    신뢰도가 추정 상한 0.5 에 묶여 게이트가 은행원 판정을 통째로 접는다.
    """
    clock = _Clock()
    clock.now_ms = 10_000
    source = TranscriptDiarization()
    resolver = SpeakerResolver(source, RoleMapper(_MarkerJudge()))
    submitted: list = []

    async def submit(utterance):
        submitted.append(utterance)

    async def publish(message):
        pass

    stt = SttSession(clock, publish, submit, resolver, diarization=source)

    async def run():
        # duration_ms 도 start_ms 도 없다. 세션 시계로 메운 시각만 남는다
        await stt._on_transcript(
            Transcript(text="중도해지 기준으로 안내드리겠습니다.", final=True, speaker_id="s1")
        )
        await stt._releasing
        await stt.aclose()

    asyncio.run(run())

    assert [(u.speaker, u.speaker_confidence) for u in submitted] == [("teller", 0.9)]
    assert submitted[0].speaker_confidence >= SPEAKER_CONFIDENCE_THRESHOLD


# --- 부팅 배선 ------------------------------------------------------------------


class _NullStream:
    async def send(self, pcm: bytes) -> None:
        pass

    async def aclose(self) -> None:
        pass


class _RecordingAdapter:
    """연 스트림과 그때 받은 화자 분리 공급원을 적어 둔다."""

    def __init__(self) -> None:
        self.keyterms: list[str] = []
        self.diarization = None

    async def open(self, on_transcript, keyterms=(), *, diarization=None):
        self.keyterms = list(keyterms)
        self.diarization = diarization
        return _NullStream()


def _start(diarization_url=None, hold_ms=2000):
    """`ws/endpoint.py` 의 `_start_stt` 를 그대로 부른다. 배선만 본다."""
    from types import SimpleNamespace

    from server.ws.endpoint import _start_stt

    judge = _MarkerJudge()
    adapter = _RecordingAdapter()
    runtime = SimpleNamespace(
        stt=adapter,
        role_judge=judge,
        pack_source=SimpleNamespace(read=lambda version: {"jargon_terms": ["만기후이자율"]}),
    )
    settings = SimpleNamespace(diarization_url=diarization_url, speaker_hold_ms=hold_ms)
    session = SimpleNamespace(pack=SimpleNamespace(pack_version=PACK_VERSION))

    async def send(message):
        pass

    conn = SimpleNamespace(send=send)
    stt = asyncio.run(
        _start_stt(
            session, SimpleNamespace(), conn, SimpleNamespace(schedule=None), runtime, settings
        )
    )
    return judge, adapter, stt


def test_the_endpoint_hands_the_session_the_runtimes_role_judge():
    """A2. 배선이 빠지면 상담마다 규칙 폴백이 서고, 화면에는 아무 차이도 안 보인다."""
    judge, adapter, stt = _start()

    assert stt is not None
    assert stt.resolver.mapper.judge is judge
    assert stt.hold_ms == 2000
    assert adapter.keyterms == ["만기후이자율"]  # 팩의 jargon_terms 가 그대로 간다
    assert adapter.diarization is stt.diarization  # 발화 단위 어댑터가 끊을 자리를 얻는다


def test_the_endpoint_puts_the_sidecar_in_when_its_url_is_set():
    """`APP_DIARIZATION_URL` 이 있으면 사이드카가 화자 분리 공급원이 된다."""
    _, _, plain = _start()
    _, _, wired = _start(diarization_url="ws://127.0.0.1:8300/ws", hold_ms=1500)

    assert isinstance(plain.diarization, TranscriptDiarization)
    assert isinstance(wired.diarization, SortformerDiarization)
    assert wired.diarization.url == "ws://127.0.0.1:8300/ws"
    assert wired.hold_ms == 1500


def test_the_segmented_adapter_is_not_built_without_a_diarization_url():
    """발화 단위 어댑터는 끊을 자리를 화자 분리 구간에서 얻는다. 공급원이 없으면 만들지 않는다.

    만들어 두면 ws 는 정상으로 열리는데 구간이 오지 않아 **전사가 조용히 멈춘다** —
    화면에는 아무 오류도 안 뜬다. 부팅에서 접어야 ws 가 stt_unavailable 을 내고
    프런트가 text 모드를 제안한다(3층 폴백).
    """
    from server.bootstrap.startup import _stt

    common = dict(stt_provider="openai_file", stt_base_url="http://127.0.0.1:8100")
    assert _stt(Settings(**common)) is None
    assert _stt(Settings(**common, diarization_url="ws://127.0.0.1:8300/ws")) is not None
