"""귀띔 세션 이벤트

scripts/gen_models.py 가 contracts/events.schema.json 에서 생성. 수동 편집 금지.
"""

from __future__ import annotations

from datetime import datetime  # noqa: F401
from typing import Annotated, Any, Literal  # noqa: F401

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter  # noqa: F401


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionStartedProduct(_Base):
    code: str
    name: str
    category: Literal["deposit", "loan"]


class SessionStartedCustomerProfile(_Base):
    type: Annotated[
        Literal["general", "professional"],
        Field(description="일반금융소비자 / 전문금융소비자. 설명의무 범위가 다르다"),
    ] = "general"
    tags: Annotated[
        list[Literal["elderly", "foreigner", "first_time", "low_literacy"]] | None,
        Field(description="취약계층 강화 절차 판단용. 로드맵 ⑨ 에서 사용"),
    ] = None


class SessionStarted(_Base):
    mode: Annotated[
        Literal["live", "replay", "trace", "text"],
        Field(description="게이트웨이 이후 동일 경로. trace 는 STT·LLM 미호출"),
    ]
    product: SessionStartedProduct
    customer_profile: SessionStartedCustomerProfile | None = None
    item_count: Annotated[int | None, Field(ge=0, description="이 팩의 필수 항목 수")] = None
    preset_id: Annotated[str | None, Field(description="심사용 프리셋에서 시작한 경우")] = None


class SessionStartedEvent(_Base):
    kind: Literal["session_started"]
    schema_version: Annotated[
        Literal["1"],
        Field(description="스키마를 바꾸면 올린다. 과거 이벤트를 읽기 위해 처음부터 넣는다."),
    ]
    event_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    session_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    seq_in_session: Annotated[
        int, Field(ge=0, description="세션 내 단조 증가. trace 재생 순서의 기준.")
    ]
    occurred_at: Annotated[
        datetime, Field(description="밀리초 포함 ISO 8601. 예 2026-09-07T11:02:14.318Z")
    ]
    pack_version: Annotated[
        str,
        Field(
            pattern="^[A-Z]{3,4}-\\d{4}\\.\\d{2}-v\\d+$",
            description="모든 이벤트에 넣는다. 낱개로 해석돼야 하고, 과거 판정을 당시 규정 기준으로 재현하려면 필수.",
        ),
    ]
    supersedes: Annotated[
        str | None,
        Field(description="이 이벤트가 대체하는 앞선 이벤트. verdict 와 assist 에서 쓴다."),
    ] = None
    session_started: SessionStarted


class Utterance(_Base):
    """확정 발화만. partial 은 저장하지 않는다."""

    speaker: Literal["teller", "customer", "system"]
    text: Annotated[
        str, Field(description="PII 마스킹 후. 주민번호·계좌·전화·카드번호는 저장 전에 가린다")
    ]
    t_ms: Annotated[
        int, Field(ge=0, description="세션 시작 기준 오프셋. 리포트 타임스탬프와 발화 재생에 쓴다")
    ]
    duration_ms: Annotated[int | None, Field(ge=0)] = None
    stt_confidence: Annotated[float | None, Field(ge=0, le=1)] = None
    speaker_confidence: Annotated[
        float | None,
        Field(ge=0, le=1, description="화자 배정 신뢰도. 낮으면 P3 에 따라 미고지 쪽으로 남긴다"),
    ] = None


class UtteranceEvent(_Base):
    kind: Literal["utterance"]
    schema_version: Annotated[
        Literal["1"],
        Field(description="스키마를 바꾸면 올린다. 과거 이벤트를 읽기 위해 처음부터 넣는다."),
    ]
    event_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    session_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    seq_in_session: Annotated[
        int, Field(ge=0, description="세션 내 단조 증가. trace 재생 순서의 기준.")
    ]
    occurred_at: Annotated[
        datetime, Field(description="밀리초 포함 ISO 8601. 예 2026-09-07T11:02:14.318Z")
    ]
    pack_version: Annotated[
        str,
        Field(
            pattern="^[A-Z]{3,4}-\\d{4}\\.\\d{2}-v\\d+$",
            description="모든 이벤트에 넣는다. 낱개로 해석돼야 하고, 과거 판정을 당시 규정 기준으로 재현하려면 필수.",
        ),
    ]
    supersedes: Annotated[
        str | None,
        Field(description="이 이벤트가 대체하는 앞선 이벤트. verdict 와 assist 에서 쓴다."),
    ] = None
    utterance: Annotated[Utterance, Field(description="확정 발화만. partial 은 저장하지 않는다.")]


class Evidence(_Base):
    """근거. P4 에 따라 인용 문자열이 원문에 실재해야 항목이 존재한다."""

    doc_id: str
    page: Annotated[int, Field(ge=1)]
    span: Annotated[str, Field(min_length=1, description="원문 인용 문자열 그대로")]
    bbox: Annotated[
        list[float] | None,
        Field(
            min_length=4,
            max_length=4,
            description="[x1,y1,x2,y2] PDF 포인트. pypdfium2 문자 좌표. 문장 하이라이트용",
        ),
    ] = None
    legal_basis: str | None = None


class Verdict(_Base):
    item_code: Annotated[
        str,
        Field(
            pattern="^[A-Z]{3,4}-[A-Z]{3}-\\d{3}$",
            description="{상품군}-{근거유형}-{연번}. 팩 버전이 올라가도 코드는 안정적이어야 과거 판정을 추적할 수 있다.",
        ),
    ]
    axis: Annotated[
        Literal["omission", "commission", "comprehension"],
        Field(description="3방향 검증. 누락 · 금지 발언 · 이해"),
    ]
    state: Annotated[
        Literal[
            "unmet",
            "partial",
            "met",
            "waived",
            "clean",
            "suspected",
            "violated",
            "explained",
            "confirmed",
        ],
        Field(description="축에 따라 허용 값이 다르다. 아래 allOf 제약 참조"),
    ]
    decided_by: Annotated[
        Literal["L1", "L2", "L3", "human"],
        Field(description="L1 규칙 · L2 의미검색 · L3 심판 · 사람. waived 는 human 만"),
    ]
    confidence: Annotated[float | None, Field(ge=0, le=1)] = None
    missing_elements: Annotated[
        list[str] | None, Field(description="요건 요소 중 아직 안 나온 것. 넛지 문구의 재료")
    ] = None
    utterance_ref: Annotated[
        str | None, Field(min_length=8, max_length=64, description="이 판정을 유발한 발화")
    ] = None
    evidence: Annotated[
        Evidence | None,
        Field(description="근거. P4 에 따라 인용 문자열이 원문에 실재해야 항목이 존재한다."),
    ] = None
    waive_reason: Annotated[
        str | None, Field(description="state=waived 일 때 사람이 남긴 사유")
    ] = None


class VerdictEvent(_Base):
    kind: Literal["verdict"]
    schema_version: Annotated[
        Literal["1"],
        Field(description="스키마를 바꾸면 올린다. 과거 이벤트를 읽기 위해 처음부터 넣는다."),
    ]
    event_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    session_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    seq_in_session: Annotated[
        int, Field(ge=0, description="세션 내 단조 증가. trace 재생 순서의 기준.")
    ]
    occurred_at: Annotated[
        datetime, Field(description="밀리초 포함 ISO 8601. 예 2026-09-07T11:02:14.318Z")
    ]
    pack_version: Annotated[
        str,
        Field(
            pattern="^[A-Z]{3,4}-\\d{4}\\.\\d{2}-v\\d+$",
            description="모든 이벤트에 넣는다. 낱개로 해석돼야 하고, 과거 판정을 당시 규정 기준으로 재현하려면 필수.",
        ),
    ]
    supersedes: Annotated[
        str | None,
        Field(description="이 이벤트가 대체하는 앞선 이벤트. verdict 와 assist 에서 쓴다."),
    ] = None
    verdict: Verdict


class AlertComparison(_Base):
    """⑤ 숫자 오류용. 말한 것과 문서의 값을 나란히"""

    said: str
    reference: str
    condition: str | None = None


class Alert(_Base):
    """은행원에게 즉시 보여야 하는 것. 우선순위는 severity 로 표현한다."""

    alert_type: Annotated[
        Literal["forbidden_phrase", "number_mismatch", "risk_signal", "term_density"],
        Field(description="금지 발언 · ⑤ 숫자 오류 · ⑦ 위험 신호 · ⑧ 용어 밀도"),
    ]
    severity: Annotated[
        Literal["critical", "warning", "info"],
        Field(
            description="critical=위험 신호(다른 것을 밀어냄) · warning=금지·숫자 · info=용어 밀도"
        ),
    ]
    message: Annotated[
        str,
        Field(
            description="고객이 화면을 볼 수 있다는 전제로 쓴다. 비난 금지. '잘못 말했습니다' 가 아니라 '설명서 기준 확인'"
        ),
    ]
    item_code: Annotated[
        str | None,
        Field(
            pattern="^[A-Z]{3,4}-[A-Z]{3}-\\d{3}$",
            description="{상품군}-{근거유형}-{연번}. 팩 버전이 올라가도 코드는 안정적이어야 과거 판정을 추적할 수 있다.",
        ),
    ] = None
    comparison: Annotated[
        AlertComparison | None, Field(description="⑤ 숫자 오류용. 말한 것과 문서의 값을 나란히")
    ] = None
    utterance_ref: Annotated[
        str | None,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ] = None
    evidence: Annotated[
        Evidence | None,
        Field(description="근거. P4 에 따라 인용 문자열이 원문에 실재해야 항목이 존재한다."),
    ] = None
    acknowledged: Annotated[
        bool,
        Field(
            description="은행원이 확인함으로 기록. 위험 신호의 후속 조치는 은행 절차이며 MVP 범위 밖"
        ),
    ] = False


class AlertEvent(_Base):
    kind: Literal["alert"]
    schema_version: Annotated[
        Literal["1"],
        Field(description="스키마를 바꾸면 올린다. 과거 이벤트를 읽기 위해 처음부터 넣는다."),
    ]
    event_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    session_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    seq_in_session: Annotated[
        int, Field(ge=0, description="세션 내 단조 증가. trace 재생 순서의 기준.")
    ]
    occurred_at: Annotated[
        datetime, Field(description="밀리초 포함 ISO 8601. 예 2026-09-07T11:02:14.318Z")
    ]
    pack_version: Annotated[
        str,
        Field(
            pattern="^[A-Z]{3,4}-\\d{4}\\.\\d{2}-v\\d+$",
            description="모든 이벤트에 넣는다. 낱개로 해석돼야 하고, 과거 판정을 당시 규정 기준으로 재현하려면 필수.",
        ),
    ]
    supersedes: Annotated[
        str | None,
        Field(description="이 이벤트가 대체하는 앞선 이벤트. verdict 와 assist 에서 쓴다."),
    ] = None
    alert: Annotated[
        Alert, Field(description="은행원에게 즉시 보여야 하는 것. 우선순위는 severity 로 표현한다.")
    ]


class Assist(_Base):
    """은행원에게 건네는 문장. outcome 은 나중에 supersedes 로 갱신한다."""

    assist_type: Annotated[
        Literal["nudge", "rephrase", "answer", "briefing", "documents"],
        Field(
            description="넛지=놓친 항목 알림 · rephrase=⑥-B 즉석 재진술 · answer=①⑩ 역질문 즉답 · briefing=② · documents=④"
        ),
    ]
    text: Annotated[str, Field(description="은행원이 그대로 읽거나 참고할 문장")]
    item_code: Annotated[
        str | None,
        Field(
            pattern="^[A-Z]{3,4}-[A-Z]{3}-\\d{3}$",
            description="{상품군}-{근거유형}-{연번}. 팩 버전이 올라가도 코드는 안정적이어야 과거 판정을 추적할 수 있다.",
        ),
    ] = None
    trigger: Annotated[
        Literal[
            "missing_item",
            "customer_reask",
            "term_density",
            "customer_question",
            "teller_typed",
            "manual_button",
            "session_start",
        ]
        | None,
        Field(description="왜 떴는지. ⑥-B 는 customer_reask·term_density·manual_button 세 트리거"),
    ] = None
    source_utterance_ref: Annotated[
        str | None,
        Field(
            min_length=8,
            max_length=64,
            description="rephrase 는 이 발화를 다시 쓴 것이다. 새 정보를 만들지 않았음을 이 참조로 확인한다",
        ),
    ] = None
    evidence: Annotated[
        Evidence | None,
        Field(description="근거. P4 에 따라 인용 문자열이 원문에 실재해야 항목이 존재한다."),
    ] = None
    outcome: Annotated[
        Literal["adopted", "ignored"] | None,
        Field(
            description="은행원이 이 표현을 실제로 썼는지. 판정 엔진이 후속 발화에서 확인한다. 처음 발행 시에는 없음"
        ),
    ] = None


class AssistEvent(_Base):
    kind: Literal["assist"]
    schema_version: Annotated[
        Literal["1"],
        Field(description="스키마를 바꾸면 올린다. 과거 이벤트를 읽기 위해 처음부터 넣는다."),
    ]
    event_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    session_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    seq_in_session: Annotated[
        int, Field(ge=0, description="세션 내 단조 증가. trace 재생 순서의 기준.")
    ]
    occurred_at: Annotated[
        datetime, Field(description="밀리초 포함 ISO 8601. 예 2026-09-07T11:02:14.318Z")
    ]
    pack_version: Annotated[
        str,
        Field(
            pattern="^[A-Z]{3,4}-\\d{4}\\.\\d{2}-v\\d+$",
            description="모든 이벤트에 넣는다. 낱개로 해석돼야 하고, 과거 판정을 당시 규정 기준으로 재현하려면 필수.",
        ),
    ]
    supersedes: Annotated[
        str | None,
        Field(description="이 이벤트가 대체하는 앞선 이벤트. verdict 와 assist 에서 쓴다."),
    ] = None
    assist: Annotated[
        Assist,
        Field(description="은행원에게 건네는 문장. outcome 은 나중에 supersedes 로 갱신한다."),
    ]


class SessionEndedSummary(_Base):
    """이벤트를 접어 만든 집계. 파생물이므로 언제든 다시 계산할 수 있다"""

    items_total: Annotated[int, Field(ge=0)]
    met: Annotated[int, Field(ge=0)]
    partial: Annotated[int, Field(ge=0)]
    unmet: Annotated[int, Field(ge=0)]
    waived: Annotated[int | None, Field(ge=0)] = None
    violations: Annotated[int | None, Field(ge=0)] = None
    alerts: Annotated[int | None, Field(ge=0)] = None
    assists_adopted: Annotated[int | None, Field(ge=0)] = None


class SessionEnded(_Base):
    reason: Literal["normal", "aborted", "timeout"]
    duration_ms: Annotated[int, Field(ge=0)]
    summary: Annotated[
        SessionEndedSummary,
        Field(description="이벤트를 접어 만든 집계. 파생물이므로 언제든 다시 계산할 수 있다"),
    ]


class SessionEndedEvent(_Base):
    kind: Literal["session_ended"]
    schema_version: Annotated[
        Literal["1"],
        Field(description="스키마를 바꾸면 올린다. 과거 이벤트를 읽기 위해 처음부터 넣는다."),
    ]
    event_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    session_id: Annotated[
        str,
        Field(
            min_length=8, max_length=64, description="ULID 권장. 시간 정렬이 되고 충돌하지 않는다."
        ),
    ]
    seq_in_session: Annotated[
        int, Field(ge=0, description="세션 내 단조 증가. trace 재생 순서의 기준.")
    ]
    occurred_at: Annotated[
        datetime, Field(description="밀리초 포함 ISO 8601. 예 2026-09-07T11:02:14.318Z")
    ]
    pack_version: Annotated[
        str,
        Field(
            pattern="^[A-Z]{3,4}-\\d{4}\\.\\d{2}-v\\d+$",
            description="모든 이벤트에 넣는다. 낱개로 해석돼야 하고, 과거 판정을 당시 규정 기준으로 재현하려면 필수.",
        ),
    ]
    supersedes: Annotated[
        str | None,
        Field(description="이 이벤트가 대체하는 앞선 이벤트. verdict 와 assist 에서 쓴다."),
    ] = None
    session_ended: SessionEnded


Event = Annotated[
    SessionStartedEvent
    | UtteranceEvent
    | VerdictEvent
    | AlertEvent
    | AssistEvent
    | SessionEndedEvent,
    Field(discriminator="kind"),
]

EVENT_KINDS: tuple[str, ...] = (
    "session_started",
    "utterance",
    "verdict",
    "alert",
    "assist",
    "session_ended",
)

event_adapter: TypeAdapter[Any] = TypeAdapter(Event)
