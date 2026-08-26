"""M1 gateway ↔ M2 engine 경계.

이 파일은 구현이 아니라 계약이다. 타입과 시그니처만 있고 본문은 없다.
M2 는 여기에 선언된 것만 밖으로 내보내고, M1 은 여기에 선언된 것만 호출한다.

세 가지 원칙이 이 파일의 모양을 정한다.

1. **M2 는 WebSocket 을 모른다.** 판정 엔진을 네트워크 없이 테스트할 수 있어야 한다.
   그래서 입력은 dataclass 이고 출력도 dataclass 다. 직렬화·전송은 M1 의 일이다.

2. **M2 는 이벤트 봉투를 만들지 않는다.** `event_id`, `seq_in_session`, `occurred_at`,
   `session_id`, `pack_version` 은 M1 이 찍는다. append 로그의 순번을 아는 쪽이 하나여야
   순번이 겹치지 않는다. M2 는 내용(payload)만 만든다.

3. **M2 는 상태를 들고 있지 않다.** 상태는 인자로 받는다. 같은 (발화, 팩, 상태)면 같은 결과가
   나와야 재생이 재생이 된다. 유일한 예외는 L3 LLM 이고, 그래서 L3 는 어댑터 뒤에 있다 (P5).

외부 의존은 모두 Protocol 로 뽑았다. 실제 구현을 끼우면 live, 녹화를 끼우면 trace 다.
게이트웨이 이후 경로가 같다는 말의 실제 내용이 이것이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, Sequence

# ---------------------------------------------------------------------------
# 값 타입. events.schema.json 과 이름·값이 1:1 로 대응한다
# ---------------------------------------------------------------------------

Axis = Literal["omission", "commission", "comprehension"]

OmissionState = Literal["unmet", "partial", "met", "waived"]
CommissionState = Literal["clean", "suspected", "violated"]
ComprehensionState = Literal["explained", "confirmed"]
VerdictState = Literal[
    "unmet", "partial", "met", "waived",
    "clean", "suspected", "violated",
    "explained", "confirmed",
]

DecidedBy = Literal["L1", "L2", "L3", "human"]
Speaker = Literal["teller", "customer", "system"]
Mode = Literal["live", "replay", "trace", "text"]
ItemType = Literal["required", "forbidden", "reference"]

AlertType = Literal["forbidden_phrase", "number_mismatch", "risk_signal", "term_density"]
Severity = Literal["critical", "warning", "info"]

AssistType = Literal["nudge", "rephrase", "answer", "briefing", "documents"]
AssistTrigger = Literal[
    "missing_item", "customer_reask", "term_density",
    "customer_question", "teller_typed", "manual_button", "session_start",
]

# 지연 예산. 초과는 버그가 아니라 설계 위반으로 다룬다
BUDGET_L1_MS = 5
BUDGET_L1_L2_MS = 20
BUDGET_L3_MS = 1500


@dataclass(frozen=True, slots=True)
class Evidence:
    """근거. span 이 원문에 실재하지 않으면 이 객체를 만들 수 없다 (P4)."""
    doc_id: str
    page: int
    span: str
    bbox: tuple[float, float, float, float] | None = None
    legal_basis: str | None = None


@dataclass(frozen=True, slots=True)
class NumericFact:
    label: str
    value: str
    unit: str
    condition: str | None = None
    tolerance: float = 0.0


@dataclass(frozen=True, slots=True)
class PackItem:
    """rulepack.schema.json 의 items[] 를 메모리로 읽은 모습."""
    code: str
    name: str
    type: ItemType
    requirement_elements: tuple[str, ...]
    evidence: Evidence
    axis: Axis | None = None
    l1_patterns: tuple[tuple[str, str], ...] = ()   # (kind, value)
    plain_language: tuple[str, ...] = ()
    numeric_facts: tuple[NumericFact, ...] = ()
    documents_required: tuple[str, ...] = ()
    forbidden_examples: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RulePack:
    """불변. 세션은 시작할 때 한 버전을 붙잡고 끝까지 바꾸지 않는다."""
    pack_version: str
    product_code: str
    product_name: str
    embedding_model: str
    embedding_dim: int
    items: tuple[PackItem, ...]

    def item(self, code: str) -> PackItem | None: ...
    def required_items(self) -> tuple[PackItem, ...]: ...
    def forbidden_items(self) -> tuple[PackItem, ...]: ...


@dataclass(frozen=True, slots=True)
class Utterance:
    """확정 발화. partial 은 여기까지 오지 않는다."""
    utterance_id: str
    speaker: Speaker
    text: str
    t_ms: int
    duration_ms: int | None = None
    stt_confidence: float | None = None
    speaker_confidence: float | None = None


# ---------------------------------------------------------------------------
# 상태. 이벤트를 접은 결과이며 원본이 아니다
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ItemState:
    item_code: str
    axis: Axis
    state: VerdictState
    decided_by: DecidedBy
    ver: int
    missing_elements: tuple[str, ...] = ()
    waive_reason: str | None = None
    first_seen_t_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SessionState:
    """M1 이 메모리에 들고 다니며 M2 에 넘긴다.

    같은 이벤트 열을 접으면 같은 SessionState 가 나와야 한다. 그래서 접는 함수도
    M2 에 둔다. 실시간 화면과 리포트가 서로 다른 접기 코드를 쓰면 두 값이 갈라진다.
    """
    session_id: str
    pack_version: str
    mode: Mode
    customer_type: Literal["general", "professional"] = "general"
    items: tuple[ItemState, ...] = ()
    recent_utterances: tuple[Utterance, ...] = ()   # L3 문맥용. 최근 N턴만
    term_density: Literal["low", "normal", "high"] = "normal"
    alert_count: int = 0

    def state_of(self, item_code: str) -> ItemState | None: ...
    def unmet_codes(self) -> tuple[str, ...]: ...


# ---------------------------------------------------------------------------
# 출력. 이벤트 payload 와 1:1. 봉투는 M1 이 씌운다
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class VerdictPayload:
    item_code: str
    axis: Axis
    state: VerdictState
    decided_by: DecidedBy
    confidence: float | None = None
    missing_elements: tuple[str, ...] = ()
    utterance_ref: str | None = None
    evidence: Evidence | None = None
    waive_reason: str | None = None
    supersedes: str | None = None
    """앞선 판정의 event_id. L1·L2 가 먼저 낸 잠정 판정을 L3 가 고칠 때 채운다."""


@dataclass(frozen=True, slots=True)
class Comparison:
    said: str
    reference: str
    condition: str | None = None


@dataclass(frozen=True, slots=True)
class AlertPayload:
    alert_type: AlertType
    severity: Severity
    message: str
    """고객이 화면을 볼 수 있다는 전제로 쓴다. 은행원을 비난하는 문구를 만들지 않는다."""
    item_code: str | None = None
    comparison: Comparison | None = None
    utterance_ref: str | None = None
    evidence: Evidence | None = None


@dataclass(frozen=True, slots=True)
class AssistPayload:
    assist_type: AssistType
    text: str
    item_code: str | None = None
    trigger: AssistTrigger | None = None
    source_utterance_ref: str | None = None
    """rephrase 는 반드시 채운다. 새 정보를 만들지 않았음을 이 참조가 증명한다."""
    evidence: Evidence | None = None
    supersedes: str | None = None


@dataclass(frozen=True, slots=True)
class TierTrace:
    """어느 층이 얼마나 걸려 무엇을 걸렀는지. 성능 회귀를 눈으로 잡기 위한 것이지
    판정 결과에는 영향이 없다. trace 모드 화면의 재료이기도 하다."""
    l1_ms: float = 0.0
    l2_ms: float = 0.0
    l3_ms: float = 0.0
    l1_hits: int = 0
    l2_candidates: int = 0
    l3_called: bool = False
    llm_tokens: int | None = None
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class JudgeResult:
    """한 발화가 만들어낸 것 전부.

    비어 있을 수 있다. 아무 항목도 건드리지 않는 발화가 대부분이고, 그때는
    아무 이벤트도 쌓이지 않는다.
    """
    verdicts: tuple[VerdictPayload, ...] = ()
    alerts: tuple[AlertPayload, ...] = ()
    assists: tuple[AssistPayload, ...] = ()
    trace: TierTrace = field(default_factory=TierTrace)


# ---------------------------------------------------------------------------
# 외부 의존. 전부 어댑터 뒤에 둔다 (P5)
# ---------------------------------------------------------------------------

class Embedder(Protocol):
    """L2 의미 검색. 로컬 모델이므로 네트워크 왕복이 없다.
    차원은 팩에 적혀 있고 여기 값과 맞지 않으면 팩 로드 단계에서 거절한다."""

    dim: int

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorIndex(Protocol):
    """pgvector 조회. 팩 버전별로 격리된 공간을 본다."""

    def search(
        self, pack_version: str, vector: Sequence[float], top_k: int
    ) -> list[tuple[str, float]]:
        """반환은 (item_code, 유사도) 목록."""
        ...


class LlmJudge(Protocol):
    """L3. 최종 판정권을 가진 쪽이고, 유일한 비결정 지점이다.

    trace 모드에서는 이 자리에 녹화 재생기를 끼운다. 그러면 같은 세션을
    LLM 호출 없이 그대로 다시 그릴 수 있다. 모델·프롬프트가 바뀌어도
    과거 세션의 화면은 변하지 않는다.
    """

    def decide(self, prompt: JudgePrompt) -> JudgeDecision: ...


@dataclass(frozen=True, slots=True)
class JudgePrompt:
    """L3 에 넘기는 것. 프롬프트 문자열이 아니라 구조로 넘긴다.
    문자열 조립을 M2 안에 두면 프롬프트를 고칠 때 계약이 흔들리지 않는다."""
    utterance_text: str
    recent_context: tuple[str, ...]
    candidate_items: tuple[PackItem, ...]
    current_states: tuple[ItemState, ...]
    customer_type: Literal["general", "professional"]
    cache_key: str
    """(pack_version, 프롬프트 내용, 모델) 해시. 같은 키면 캐시를 쓴다."""


@dataclass(frozen=True, slots=True)
class JudgeDecision:
    verdicts: tuple[VerdictPayload, ...] = ()
    alerts: tuple[AlertPayload, ...] = ()
    assists: tuple[AssistPayload, ...] = ()
    tokens: int | None = None
    from_cache: bool = False


class DecisionCache(Protocol):
    """L3 응답 캐시. 같은 발화·같은 팩이면 두 번 묻지 않는다.
    시연 반복과 replay 의 비용·지연이 여기서 사라진다."""

    def get(self, cache_key: str) -> JudgeDecision | None: ...
    def put(self, cache_key: str, decision: JudgeDecision) -> None: ...


# ---------------------------------------------------------------------------
# M2 가 밖으로 내보내는 것
# ---------------------------------------------------------------------------

class Engine(Protocol):
    """M1 이 아는 M2 의 전부."""

    def load_pack(self, pack_version: str) -> RulePack:
        """팩을 읽어 L1 패턴을 컴파일하고 임베딩 차원을 검사한다.
        세션마다 다시 읽지 않도록 M1 이 캐시한다."""
        ...

    def initial_state(
        self,
        session_id: str,
        pack: RulePack,
        mode: Mode,
        customer_type: Literal["general", "professional"] = "general",
    ) -> SessionState:
        """필수 항목 전부 unmet, 금지 항목 전부 clean 인 출발점.
        화면의 첫 체크리스트가 이것이다."""
        ...

    def judge(
        self, utterance: Utterance, pack: RulePack, state: SessionState
    ) -> JudgeResult:
        """핵심. L1 → L2 → L3 순서로 좁히고 판정을 만든다.

        L1·L2 만으로 확실한 것은 즉시 반환하고, L3 가 필요한 것은 잠정 판정을
        먼저 낸 뒤 나중에 supersedes 로 고친다. 그래서 이 함수는 두 번 결과를
        낼 수 있고, 두 번째 호출은 `refine` 이다.

        판정이 갈리지 않으면 빈 JudgeResult 를 돌려준다. 이 경우 M1 은
        아무것도 저장하지 않는다.
        """
        ...

    async def refine(
        self, utterance: Utterance, pack: RulePack, state: SessionState
    ) -> JudgeResult:
        """L3 보정. judge() 가 잠정으로 남긴 것을 다시 판정한다.
        비동기인 이유는 이것만 느리기 때문이다. 화면은 기다리지 않는다."""
        ...

    def apply(self, state: SessionState, result: JudgeResult) -> SessionState:
        """판정을 상태에 반영한다. 새 객체를 돌려주고 인자를 고치지 않는다.
        같은 result 를 두 번 적용해도 같은 상태가 나와야 한다 (멱등)."""
        ...

    def fold(self, events: Sequence[dict]) -> SessionState:
        """이벤트 열 → 상태. trace 재생과 리포트가 같은 함수를 쓴다.
        supersede 된 이벤트는 건너뛴다."""
        ...

    def answer(
        self, question: str, pack: RulePack, state: SessionState
    ) -> AssistPayload | None:
        """기능 ①⑩. 근거를 못 찾으면 None 을 돌려준다.
        근거 없는 문장을 만들어 내보내지 않는다 (P4)."""
        ...

    def rephrase(
        self, source: Utterance, pack: RulePack, state: SessionState
    ) -> AssistPayload | None:
        """기능 ⑥-B. 직전 은행원 발화를 쉬운 말로 다시 쓴다.
        원문 발화에 없던 내용은 넣지 않는다. source_utterance_ref 가 그 제약의 표시다."""
        ...

    def briefing(
        self, pack: RulePack, customer_type: Literal["general", "professional"]
    ) -> AssistPayload:
        """기능 ②. 팩 발행 시 미리 만들어 두므로 실시간 호출이 아니다."""
        ...

    def documents(self, pack: RulePack, state: SessionState) -> AssistPayload:
        """기능 ④. 팩의 reference 항목에서 조립한다. LLM 을 쓰지 않는다."""
        ...


# ---------------------------------------------------------------------------
# 조립. M1 이 부팅할 때 한 번 부른다
# ---------------------------------------------------------------------------

def build_engine(
    embedder: Embedder,
    index: VectorIndex,
    llm: LlmJudge,
    cache: DecisionCache,
) -> Engine:
    """의존을 밖에서 넣는다. 테스트는 네 개를 다 가짜로 바꿔 끼운다.

    - live   실제 임베더 · pgvector · LLM · 캐시
    - trace  실제 임베더 · pgvector · 녹화 재생기 · 캐시
    - 단위테스트  전부 가짜. 네트워크·DB·모델 없이 판정 로직만 검사한다
    """
    raise NotImplementedError
