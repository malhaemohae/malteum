"""화자 단계. 화자분리 번호를 발화에 붙이고, 그 번호를 역할로 매핑한다.

STT 와 `pipeline.submit_utterance` 사이, 엔진 바깥에 둔다. 엔진은 `Utterance.speaker`
와 `speaker_confidence` 만 소비하므로 이 단계가 바뀌어도 엔진 계약은 그대로다.

## 두 가지 일

    접착   발화 구간과 가장 많이 겹치는 화자 번호를 고른다      SpeakerResolver
    매핑   번호 → teller · customer · other 를 LLM 로 정한다   RoleMapper · RoleJudge

**첫 화자 규칙을 쓰지 않는다.** "먼저 말한 쪽이 고객" 은 대본에서만 참이고 실제 상담
에서는 은행원이 먼저 인사한다. 그리고 화자분리는 실제 사람 수보다 번호를 더 만든다
(같은 사람이 두 번호로 갈리거나 제3자가 끼어든다). 그래서 새 번호가 나올 때마다 그
번호의 발화와 이미 역할이 정해진 번호들의 최근 발화를 함께 LLM 에 주고 역할을 받는다.

## 확정될 때까지 2초까지만 붙잡는다 (DEC-7)

LLM 왕복은 1~2초다(실측 CTX-005). 새 번호의 첫 발화를 잠정 라벨로 그냥 내보내면 그
줄의 필수 고지·위험 신호가 통째로 게이트에 접히므로, 역할이 확정될 때까지 **상한
2초**(`SPEAKER_HOLD_MS`)만 붙잡았다가 내보낸다. 상한을 넘기면 잠정 라벨(신뢰도 0.2)로
내보내고, 확정된 뒤에 이전 발화를 다시 판정하지는 않는다. 잠정 규칙은 "확정된 번호가
하나뿐이면 그 반대 역할, 아니면 teller" 다 — 근거가 없을 때 미고지 쪽으로 두는 기존
정책(리스크 3 · P3)을 따른다.

붙잡는 동안 순서가 뒤바뀌면 리포트의 시간 순서가 무너진다. 큐를 세우고 앞에서부터
비우는 일은 이 파일이 아니라 `session.py` 가 한다 — 여기는 "이 번호가 확정될 때까지
기다린다" 하나만 맡는다.

## 신뢰도가 하는 일

`engine/tiers/l1/gate.py` 가 `speaker_confidence` 0.6 미만인 은행원 발화의 판정을
접는다. 그래서 이 파일의 신뢰도 값들은 그 임계를 기준으로 정했다 — 확신이 없으면
게이트가 접도록 임계 아래로 싣는다. 잘못된 met 가 잘못된 unmet 보다 위험하다(P3).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from server.services.stt.diarization import (
    DiarizationSource,
    SpeakerSegment,
    TranscriptDiarization,
)

log = logging.getLogger(__name__)

Role = Literal["teller", "customer", "other"]

# 근거가 없을 때 두는 역할. 판정 대상이 은행원 발화라, 고객 말을 은행원 것으로 보는 쪽이
# 미고지를 남긴다 — 반대는 위험 신호 경보를 지운다 (SCRIPT.md 1장)
DEFAULT_ROLE: Role = "teller"
OPPOSITE: dict[Role, Role] = {"teller": "customer", "customer": "teller"}

# 게이트 임계(gate.py SPEAKER_CONFIDENCE_THRESHOLD)와 같은 값. 이보다 낮은 신뢰도로
# 역할을 확정하면 어차피 은행원 판정이 접히므로, 확정선을 게이트에 맞춘다
ROLE_CONFIDENCE_MIN = 0.6
# 최초 1회 + 저신뢰가 이어질 때 1회 더 + 재추론 1회. 세 번째 답은 신뢰도와 무관하게 확정한다.
# 상한이 없으면 애매한 번호 하나가 발화마다 LLM 을 부른다
MAX_ASKS = 3
# LLM 에 주는 발화 수. 새 번호는 최근 2개, 확정 번호는 각각 최근 2개(재추론 때는 4개)
NEW_RECENT = 2
KNOWN_RECENT = 2
KNOWN_RECENT_WIDE = 4
_RECENT_MAX = max(NEW_RECENT, KNOWN_RECENT_WIDE)

# 확정 전 잠정 라벨의 신뢰도. 게이트 아래라 은행원 판정은 접힌다
PROVISIONAL_CONFIDENCE = 0.2
# 화자분리 공급원이 아예 없을 때. **계약 기본값 None 이고 0.0 이 아니다.** 0.0 을 실으면
# 게이트가 은행원 발화를 전부 접어 화자분리가 없는 배포 경로(Deepgram · replay)에서
# 필수 고지·금지 발언 판정이 통째로 사라진다. None 은 "잴 수 없었다" 라서 게이트가
# 신뢰도를 보지 않고 예전대로 판정한다 (gate.py `conf is not None`)
NO_DIARIZATION_CONFIDENCE: float | None = None
# LLM 없이 규칙으로만 답할 때. 확정은 되지만 게이트는 접는다
FALLBACK_CONFIDENCE = 0.3
# DEC-7. 새 번호의 발화를 역할이 확정될 때까지 붙잡는 상한. LLM 왕복 실측이 1~2초라
# (CTX-005) 2초면 대개 정식 라벨로 나가고, 넘기면 잠정 라벨로 흘려보낸다
SPEAKER_HOLD_MS = 2000

# 겹치는 구간이 없을 때 가장 가까운 구간을 얼마까지 끌어다 쓰나. 대본이 화자가 바뀌는
# 자리마다 무음 1초 이상을 두므로(SCRIPT.md `audio.min_gap_ms`), 1초를 넘겨 붙이면
# 옆 화자의 구간을 끌어온다
NEAREST_GAP_MS = 1000
# 그렇게 끌어다 쓴 화자의 점유율. 겹침이 없어 추정한 것이므로 게이트 아래로 둔다
NEAREST_SHARE = 0.5
# 2위 겹침이 1위의 이 비율 이상이면 두 화자가 섞인 것으로 보고 점유율을 신뢰도에 싣는다.
# 스쳐 지나간 한두 마디까지 신뢰도를 깎지 않도록 문턱을 둔다
MIXED_RATIO = 0.35


@dataclass(frozen=True, slots=True)
class KnownSpeaker:
    """역할이 이미 정해진 번호. 새 번호를 판정할 때 대조군으로 함께 준다."""

    speaker_id: str
    role: Role
    recent: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoleRequest:
    speaker_id: str
    recent: tuple[str, ...]
    known: tuple[KnownSpeaker, ...]


@dataclass(frozen=True, slots=True)
class RoleVerdict:
    role: Role
    confidence: float
    reason: str = ""


class RoleJudge(Protocol):
    async def decide(self, request: RoleRequest) -> RoleVerdict:
        """이 번호가 은행원인지 고객인지 제3자인지 정한다.

        발화를 붙잡지 않으려고 배경에서 부른다. 실물 구현은 LiteLLM 이라 동기 호출을
        스레드로 넘긴다(`role_judge.py`).
        """
        ...


class RuleRoleJudge:
    """LLM 설정이 없을 때의 폴백. 확정 번호가 하나면 그 반대, 아니면 teller.

    문장을 읽지 않으므로 신뢰도를 낮게 둔다 — 게이트가 은행원 판정을 접고, 고객
    쪽 위험 신호·되물음은 게이트가 신뢰도를 보지 않아 그대로 돈다.
    """

    async def decide(self, request: RoleRequest) -> RoleVerdict:
        roles = {k.role for k in request.known if k.role in OPPOSITE}
        if len(roles) == 1:
            return RoleVerdict(
                OPPOSITE[roles.pop()], FALLBACK_CONFIDENCE, "규칙 폴백: 확정된 번호의 반대"
            )
        return RoleVerdict(DEFAULT_ROLE, FALLBACK_CONFIDENCE, "규칙 폴백: 근거 없음 → 미고지 쪽")


@dataclass
class _Number:
    """번호 하나의 상태. `settled` 가 True 면 다시 묻지 않는다."""

    recent: deque[str]
    role: Role | None = None
    confidence: float = 0.0
    asks: int = 0
    settled: bool = False
    asking: bool = False
    # 확정되는 순간 열린다. 이 번호의 발화를 붙잡고 있는 쪽(DEC-7)이 여기서 기다린다
    decided: asyncio.Event = field(default_factory=asyncio.Event)


class RoleMapper:
    """화자 번호 → 역할 표. LLM 로 갱신하고, 한 번 확정한 번호는 다시 묻지 않는다.

    **재추론 조건.** 답의 신뢰도가 `ROLE_CONFIDENCE_MIN` 미만이면 확정으로 치지 않고,
    그 번호의 발화가 더 쌓이면 한 번 더 묻는다. 낮은 신뢰도가 두 번 연속이면 세 번째로
    문맥을 넓혀(확정 번호들의 최근 발화를 두 배로) 재추론을 한 번 걸고, 그 답을 신뢰도와
    무관하게 확정한다. 애매한 번호가 LLM 을 무한히 부르지 않게 하는 상한이기도 하다.
    """

    def __init__(self, judge: RoleJudge | None = None) -> None:
        self.judge: RoleJudge = judge if judge is not None else RuleRoleJudge()
        self._numbers: dict[str, _Number] = {}
        self._tasks: set[asyncio.Task] = set()

    def observe(self, speaker_id: str, text: str) -> None:
        """이 번호가 한 말을 쌓고, 아직 역할이 없으면 추론을 건다(기다리지 않는다)."""
        number = self._numbers.get(speaker_id)
        if number is None:
            number = self._numbers[speaker_id] = _Number(deque(maxlen=_RECENT_MAX))
        number.recent.append(text)
        if number.settled or number.asking:
            return
        number.asking = True
        task = asyncio.create_task(self._ask(speaker_id, number))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def role_of(self, speaker_id: str) -> tuple[Role, float] | None:
        """확정된 역할과 그 신뢰도. 아직 확정 전이면 None."""
        number = self._numbers.get(speaker_id)
        if number is None or not number.settled or number.role is None:
            return None
        return number.role, number.confidence

    def provisional(self) -> Role:
        """확정 전에 붙일 잠정 라벨. 확정된 번호가 하나뿐이면 그 반대, 아니면 teller."""
        roles = {n.role for n in self._numbers.values() if n.settled and n.role in OPPOSITE}
        if len(roles) == 1:
            return OPPOSITE[roles.pop()]
        return DEFAULT_ROLE

    async def wait_settled(self, speaker_id: str, timeout_s: float) -> bool:
        """이 번호의 역할이 확정되기를 상한만큼 기다린다 (DEC-7). 넘기면 False.

        기다리는 쪽은 발화 하나를 붙잡고 있다. 상한을 넘겨도 예외를 올리지 않는 이유는
        "못 기다렸다" 가 정상 경로이기 때문이다 — 잠정 라벨로 내보내면 된다.
        """
        number = self._numbers.get(speaker_id)
        if number is None:
            return False
        if number.settled:
            return True
        try:
            await asyncio.wait_for(number.decided.wait(), timeout_s)
        except TimeoutError:
            return False
        return True

    async def pending(self) -> None:
        """진행 중인 역할 추론이 끝날 때까지 기다린다. 테스트와 재생에서 쓴다."""
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        """진행 중인 추론을 거두고 끝낸다.

        세션이 닫힌 뒤에 오는 답은 붙일 발화가 없다. 그런데 실물 판별기의 타임아웃은
        30초라(`role_judge.py`), 그냥 기다리면 소켓이 끊긴 뒤에도 상담 하나가 그만큼
        서버에 남는다. 그래서 기다리지 않고 취소한다.
        """
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _ask(self, speaker_id: str, number: _Number) -> None:
        """한 번 묻고 그 답으로 역할표를 갱신한다.

        배경 태스크라 예외를 밖으로 내보내면 아무도 보지 못한다. 판정뿐 아니라 확정·
        로깅에서 터진 것까지 여기서 잡는다 — `asking` 을 못 풀면 그 번호는 두 번 다시
        묻히지 않고 잠정 라벨에 갇힌다.
        """
        verdict: RoleVerdict | None = None
        try:
            wide = number.asks + 1 >= MAX_ASKS  # 마지막 한 번은 문맥을 넓혀 재추론한다
            verdict = await self.judge.decide(
                RoleRequest(
                    speaker_id=speaker_id,
                    recent=tuple(number.recent)[-NEW_RECENT:],
                    known=self._known(speaker_id, KNOWN_RECENT_WIDE if wide else KNOWN_RECENT),
                )
            )
        except asyncio.CancelledError:
            number.asking = False
            raise
        except Exception as e:  # noqa: BLE001  판정 하나가 상담을 끊지 않게 한다
            log.warning("화자 역할 추론 실패 (%s): %s: %s", speaker_id, type(e).__name__, e)
        try:
            number.asks += 1
            if verdict is None:
                if number.asks >= MAX_ASKS:
                    # 더 물어도 같을 것이다. 규칙 폴백과 같은 자리에 낮은 신뢰도로 세운다
                    self._settle(
                        speaker_id, number, RoleVerdict(self.provisional(), 0.0, "추론 실패")
                    )
            elif verdict.confidence >= ROLE_CONFIDENCE_MIN or number.asks >= MAX_ASKS:
                self._settle(speaker_id, number, verdict)
            else:
                number.role, number.confidence = verdict.role, verdict.confidence
                log.info(
                    "화자 역할 미확정 (%s): %s conf=%.2f (%d/%d) — %s",
                    speaker_id,
                    verdict.role,
                    verdict.confidence,
                    number.asks,
                    MAX_ASKS,
                    verdict.reason,
                )
        except Exception as e:  # noqa: BLE001  확정·로깅이 터져도 다음 발화는 다시 묻는다
            log.warning("화자 역할 갱신 실패 (%s): %s: %s", speaker_id, type(e).__name__, e)
        finally:
            number.asking = False

    def _settle(self, speaker_id: str, number: _Number, verdict: RoleVerdict) -> None:
        number.role, number.confidence, number.settled = verdict.role, verdict.confidence, True
        number.decided.set()  # 이 번호의 발화를 붙잡고 있던 쪽을 깨운다
        log.info(
            "화자 역할 확정 (%s): %s conf=%.2f — %s",
            speaker_id,
            verdict.role,
            verdict.confidence,
            verdict.reason,
        )

    def _known(self, exclude: str, recent: int) -> tuple[KnownSpeaker, ...]:
        return tuple(
            KnownSpeaker(sid, n.role, tuple(n.recent)[-recent:])
            for sid, n in self._numbers.items()
            if sid != exclude and n.settled and n.role is not None
        )


@dataclass(frozen=True, slots=True)
class Attribution:
    """발화 하나에 붙은 화자. `role` 이 other 면 부르는 쪽이 submit 하지 않는다.

    `confidence` 가 None 이면 "잴 수 없었다" 다 — 화자분리 공급원이 없는 경우뿐이고,
    게이트는 그 값을 보지 않고 예전대로 판정한다.
    """

    role: Role
    confidence: float | None
    speaker_id: str | None
    provisional: bool


# 화자분리 공급원이 없을 때. 기존 동작(teller 고정)에 계약 기본값 None 을 그대로 싣는다.
# 문장만 보고 화자를 추정하는 예비 신호는 여기에 붙는다 — 이번 범위 밖이다
NO_SPEAKER = Attribution(DEFAULT_ROLE, NO_DIARIZATION_CONFIDENCE, None, provisional=False)


class SpeakerResolver:
    """발화 → (역할, 신뢰도). 화자분리 구간에 붙이고 역할표를 거친다."""

    def __init__(
        self,
        source: DiarizationSource | None = None,
        mapper: RoleMapper | None = None,
    ) -> None:
        self.source: DiarizationSource = source if source is not None else TranscriptDiarization()
        self.mapper = mapper if mapper is not None else RoleMapper()

    def resolve(self, text: str, start_ms: int, duration_ms: int | None) -> Attribution:
        """붙잡지 않고 지금 아는 것으로 붙인다."""
        picked = self.pick(text, start_ms, duration_ms)
        if picked is None:
            return NO_SPEAKER
        return self.label(*picked)

    def pick(self, text: str, start_ms: int, duration_ms: int | None) -> tuple[str, float] | None:
        """발화를 화자 번호에 붙이고 그 번호의 역할 추론을 건다(기다리지 않는다).

        붙잡기(DEC-7)는 이 다음이다. 추론을 여기서 먼저 걸어 두어야 붙잡는 시간이
        LLM 왕복과 겹친다 — 큐 차례가 왔을 때 걸면 상한 2초를 그만큼 헛되이 쓴다.
        """
        picked = self.speaker_of(start_ms, duration_ms)
        if picked is None:
            return None
        self.mapper.observe(picked[0], text)
        return picked

    def label(self, speaker_id: str, share: float) -> Attribution:
        """지금 역할표에 있는 값으로 라벨을 만든다. 확정 전이면 잠정 라벨이다."""
        known = self.mapper.role_of(speaker_id)
        if known is None:
            return Attribution(
                self.mapper.provisional(), PROVISIONAL_CONFIDENCE, speaker_id, provisional=True
            )
        role, confidence = known
        return Attribution(role, round(min(confidence, share), 3), speaker_id, provisional=False)

    async def hold(self, speaker_id: str | None, share: float, timeout_s: float) -> Attribution:
        """DEC-7. 역할이 확정될 때까지 상한 안에서 붙잡았다가 붙인다.

        상한을 넘기면 잠정 라벨로 내보낸다. 확정 뒤 소급 재판정은 하지 않는다.
        """
        if speaker_id is None:
            return NO_SPEAKER
        if timeout_s > 0:
            await self.mapper.wait_settled(speaker_id, timeout_s)
        return self.label(speaker_id, share)

    def speaker_of(self, start_ms: int, duration_ms: int | None) -> tuple[str, float] | None:
        """가장 많이 겹치는 화자 번호와 그 번호가 차지한 몫.

        몫은 신뢰도의 상한이다. 한 화자로만 되어 있으면 1.0 이고, 두 번호가 비슷하게
        섞이면 점유율만큼 내려가 게이트가 접는다 — 경계가 흔들린 발화를 잘못된 축으로
        판정하는 것보다 안 하는 편이 낫다.
        """
        segments = self.source.segments()
        if not segments:
            return None
        end_ms = max(start_ms + (duration_ms or 0), start_ms + 1)
        overlap: dict[str, int] = {}
        for s in segments:
            shared = min(s.end_ms, end_ms) - max(s.start_ms, start_ms)
            if shared > 0:
                overlap[s.speaker_id] = overlap.get(s.speaker_id, 0) + shared
        if not overlap:
            return _nearest(segments, start_ms, end_ms)
        best = max(overlap, key=lambda sid: overlap[sid])
        ranked = sorted(overlap.values(), reverse=True)
        runner_up = ranked[1] if len(ranked) > 1 else 0
        if runner_up < MIXED_RATIO * ranked[0]:
            return best, 1.0
        return best, round(ranked[0] / sum(ranked), 3)

    async def pending(self) -> None:
        await self.mapper.pending()

    async def aclose(self) -> None:
        await self.mapper.aclose()


def _nearest(
    segments: Sequence[SpeakerSegment], start_ms: int, end_ms: int
) -> tuple[str, float] | None:
    """겹치는 구간이 없을 때 가장 가까운 구간. 거리 한계 밖이면 화자를 지어내지 않는다.

    한계와 **같은** 거리도 밖으로 본다. 대본이 화자가 바뀌는 자리마다 무음을 1초
    "이상" 두므로, 정확히 1초 떨어진 구간은 옆 화자의 것일 수 있다.
    """
    best: str | None = None
    nearest = NEAREST_GAP_MS
    for s in segments:
        gap = max(s.start_ms - end_ms, start_ms - s.end_ms, 0)
        if gap < nearest:
            best, nearest = s.speaker_id, gap
    if best is None:
        return None
    return best, NEAREST_SHARE
