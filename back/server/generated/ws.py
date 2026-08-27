"""말틈 WebSocket 프로토콜

scripts/gen_models.py 가 contracts/ws_protocol.schema.json 에서 생성. 수동 편집 금지.
"""

from __future__ import annotations

from datetime import datetime  # noqa: F401
from typing import Annotated, Any, Literal  # noqa: F401

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter  # noqa: F401


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HelloCustomerProfile(_Base):
    type: Literal["general", "professional"] | None = None
    tags: list[str] | None = None


class Hello(_Base):
    """replay·trace 는 hello 를 받은 서버가 ready 직후 자동으로 재생을 시작한다. 별도 시작 메시지는 없다."""

    t: Literal["hello"]
    mode: Literal["live", "replay", "trace", "text"]
    product_code: str | None = None
    preset_id: Annotated[
        str | None, Field(description="프리셋으로 시작하면 product·customer 를 서버가 채운다")
    ] = None
    customer_profile: HelloCustomerProfile | None = None
    session_id: Annotated[str | None, Field(description="이어 붙일 세션. 없으면 서버가 만든다")] = (
        None
    )


class Resume(_Base):
    t: Literal["resume"]
    session_id: str
    from_seq: Annotated[
        int, Field(ge=0, description="마지막으로 받은 s2c seq. 서버는 그 다음부터 다시 보낸다")
    ]


class TextUtterance(_Base):
    """text 모드와 ⑪ 수동 진행에서 쓴다. STT 없이 판정 경로를 그대로 탄다."""

    t: Literal["text_utterance"]
    text: Annotated[str, Field(min_length=1)]
    speaker: Annotated[
        Literal["teller", "customer"],
        Field(description="text 모드에서 화자를 명시. STT 가 없으니 클라이언트가 알려준다"),
    ] = "teller"


class Ask(_Base):
    """⑩ 텍스트 질의. 발화가 아니라 은행원의 질문이므로 utterance 로 저장하지 않는다."""

    t: Literal["ask"]
    question: Annotated[str, Field(min_length=1)]


class AssistRequest(_Base):
    """⑥-B 수동 버튼. 자동 트리거가 놓쳤을 때 사람이 보완한다 (P3 방향)."""

    t: Literal["assist_request"]
    assist_type: Literal["rephrase", "documents", "briefing"]
    item_code: str | None = None


class MarkMet(_Base):
    """⑪ 수동 체크. 사람이 항목을 직접 met 로 올린다. 서버는 decided_by=human verdict 로 기록하며, 사람 결정은 L3 가 뒤집지 않는다. undo 는 human 이 만든 met 만 무를 수 있다. 엔진(L1~L3)이 만든 met 는 사람도 엔진도 되돌리지 않는다 (P3: met→unmet 자동 되돌림 금지 유지)."""

    t: Literal["mark_met"]
    item_code: str
    undo: Annotated[
        bool, Field(description="true 면 자기가 올린 human met 를 무른다 (실수 클릭 복구)")
    ] = False


class MarkWaived(_Base):
    """waived 는 사람만 설정한다. 사유 없이는 받지 않는다."""

    t: Literal["mark_waived"]
    item_code: str
    reason: Annotated[str, Field(min_length=1)]


class Acknowledge(_Base):
    """경보 확인함. 특히 ⑦ 위험 신호의 기록."""

    t: Literal["acknowledge"]
    alert_ref: str


class End(_Base):
    t: Literal["end"]


class Pong(_Base):
    t: Literal["pong"]


class ReadyItems(_Base):
    item_code: str
    name: str
    axis: Literal["omission", "commission", "comprehension"]
    state: str
    required: bool = True
    plain_language: Annotated[
        list[str] | None, Field(description="⑥-A 쉬운 말. 미리 승인된 문장이므로 화면이 바로 쓴다")
    ] = None


class Ready(_Base):
    t: Literal["ready"]
    seq: Annotated[
        int,
        Field(
            ge=0,
            description="세션 단위 단조 증가. 재접속해도 이어진다 (연결 단위로 리셋되면 resume 의 from_seq 가 무의미해짐). 서버는 세션별 s2c 로그를 유지해 from_seq 이후를 재전송한다. 저장물에는 넣지 않는다",
        ),
    ]
    session_id: str
    pack_version: str
    mode: Literal["live", "replay", "trace", "text"] | None = None
    items: Annotated[
        list[ReadyItems],
        Field(description="체크리스트 초기 상태. 화면이 이걸로 우측 패널을 그린다"),
    ]


class Partial(_Base):
    """중간 전사. 저장하지 않는다. 화면에 흘려 보내 시스템이 듣고 있음을 보여준다."""

    t: Literal["partial"]
    seq: Annotated[
        int,
        Field(
            ge=0,
            description="세션 단위 단조 증가. 재접속해도 이어진다 (연결 단위로 리셋되면 resume 의 from_seq 가 무의미해짐). 서버는 세션별 s2c 로그를 유지해 from_seq 이후를 재전송한다. 저장물에는 넣지 않는다",
        ),
    ]
    text: str
    speaker: Literal["teller", "customer", "unknown"] | None = None


class Utterance(_Base):
    t: Literal["utterance"]
    seq: Annotated[
        int,
        Field(
            ge=0,
            description="세션 단위 단조 증가. 재접속해도 이어진다 (연결 단위로 리셋되면 resume 의 from_seq 가 무의미해짐). 서버는 세션별 s2c 로그를 유지해 from_seq 이후를 재전송한다. 저장물에는 넣지 않는다",
        ),
    ]
    event_id: Annotated[str, Field(description="events 의 event_id. 화면이 근거 조회에 쓴다")]
    speaker: Literal["teller", "customer", "system"]
    text: str
    t_ms: Annotated[int, Field(ge=0)]


class Verdict(_Base):
    t: Literal["verdict"]
    seq: Annotated[
        int,
        Field(
            ge=0,
            description="세션 단위 단조 증가. 재접속해도 이어진다 (연결 단위로 리셋되면 resume 의 from_seq 가 무의미해짐). 서버는 세션별 s2c 로그를 유지해 from_seq 이후를 재전송한다. 저장물에는 넣지 않는다",
        ),
    ]
    event_id: str
    item_code: str
    axis: Literal["omission", "commission", "comprehension"]
    state: str
    ver: Annotated[
        int,
        Field(
            ge=1,
            description="항목별 판정 버전. L1·L2 가 ver 1 로 먼저 그리고 L3 가 ver 2 로 고친다. 프런트는 큰 ver 만 채택해 순서 뒤바뀜을 흡수한다",
        ),
    ]
    decided_by: Literal["L1", "L2", "L3", "human"] | None = None
    missing_elements: list[str] | None = None
    evidence_ref: Annotated[
        str | None, Field(description="⑭ 근거 원문 오버레이를 열 때 쓰는 참조")
    ] = None


class AlertComparison(_Base):
    said: str | None = None
    reference: str | None = None
    condition: str | None = None


class Alert(_Base):
    t: Literal["alert"]
    seq: Annotated[
        int,
        Field(
            ge=0,
            description="세션 단위 단조 증가. 재접속해도 이어진다 (연결 단위로 리셋되면 resume 의 from_seq 가 무의미해짐). 서버는 세션별 s2c 로그를 유지해 from_seq 이후를 재전송한다. 저장물에는 넣지 않는다",
        ),
    ]
    event_id: str
    alert_type: Literal["forbidden_phrase", "number_mismatch", "risk_signal", "term_density"]
    severity: Literal["critical", "warning", "info"]
    message: Annotated[str, Field(description="고객이 봐도 무해한 문구")]
    item_code: str | None = None
    comparison: AlertComparison | None = None
    evidence_ref: str | None = None


class Assist(_Base):
    t: Literal["assist"]
    seq: Annotated[
        int,
        Field(
            ge=0,
            description="세션 단위 단조 증가. 재접속해도 이어진다 (연결 단위로 리셋되면 resume 의 from_seq 가 무의미해짐). 서버는 세션별 s2c 로그를 유지해 from_seq 이후를 재전송한다. 저장물에는 넣지 않는다",
        ),
    ]
    event_id: str
    assist_type: Literal["nudge", "rephrase", "answer", "briefing", "documents"]
    text: str
    ver: Annotated[int, Field(ge=1)]
    item_code: str | None = None
    evidence_ref: str | None = None
    outcome: Literal["adopted", "ignored"] | None = None


class Progress(_Base):
    """집계는 서버가 한다. 프런트가 이벤트를 접지 않게 해서 상태 계산 로직이 두 곳에 생기는 것을 막는다."""

    t: Literal["progress"]
    seq: Annotated[
        int,
        Field(
            ge=0,
            description="세션 단위 단조 증가. 재접속해도 이어진다 (연결 단위로 리셋되면 resume 의 from_seq 가 무의미해짐). 서버는 세션별 s2c 로그를 유지해 from_seq 이후를 재전송한다. 저장물에는 넣지 않는다",
        ),
    ]
    met: Annotated[int, Field(ge=0)]
    partial: Annotated[int | None, Field(ge=0)] = None
    items_total: Annotated[
        int,
        Field(
            ge=0,
            description="필수(required) 항목 수만. 금지·위험 항목은 집계에 안 들어간다. ready 의 items 개수(금지 포함)와 다르니 프런트가 이 값을 분모로 쓴다",
        ),
    ]
    remaining: Annotated[
        list[str] | None, Field(description="미고지 항목 이름. 넛지 띠에 나열한다")
    ] = None
    term_density: Annotated[
        Literal["low", "normal", "high"] | None, Field(description="⑧. 경보가 아니라 상태 게이지")
    ] = None


class Ended(_Base):
    t: Literal["ended"]
    seq: Annotated[
        int,
        Field(
            ge=0,
            description="세션 단위 단조 증가. 재접속해도 이어진다 (연결 단위로 리셋되면 resume 의 from_seq 가 무의미해짐). 서버는 세션별 s2c 로그를 유지해 from_seq 이후를 재전송한다. 저장물에는 넣지 않는다",
        ),
    ]
    session_id: str
    summary: dict[str, Any]
    report_url: str | None = None


class Error(_Base):
    t: Literal["error"]
    seq: Annotated[
        int,
        Field(
            ge=0,
            description="세션 단위 단조 증가. 재접속해도 이어진다 (연결 단위로 리셋되면 resume 의 from_seq 가 무의미해짐). 서버는 세션별 s2c 로그를 유지해 from_seq 이후를 재전송한다. 저장물에는 넣지 않는다",
        ),
    ]
    code: Annotated[
        Literal[
            "stt_unavailable",
            "pack_not_found",
            "invalid_message",
            "session_expired",
            "rate_limited",
            "internal",
        ],
        Field(description="stt_unavailable 이면 프런트가 text 모드 전환을 제안한다 (3층 폴백)"),
    ]
    message: str
    retryable: bool = False


class Ping(_Base):
    """하트비트. 터널링의 idle timeout 과 NAT 테이블 만료를 함께 막는다. 30초 간격 권장. 클라이언트는 pong 으로 답한다."""

    t: Literal["ping"]
    seq: Annotated[
        int,
        Field(
            ge=0,
            description="세션 단위 단조 증가. 재접속해도 이어진다 (연결 단위로 리셋되면 resume 의 from_seq 가 무의미해짐). 서버는 세션별 s2c 로그를 유지해 from_seq 이후를 재전송한다. 저장물에는 넣지 않는다",
        ),
    ]


C2s = Annotated[
    Hello
    | Resume
    | TextUtterance
    | Ask
    | AssistRequest
    | MarkMet
    | MarkWaived
    | Acknowledge
    | End
    | Pong,
    Field(discriminator="t"),
]
S2c = Annotated[
    Ready | Partial | Utterance | Verdict | Alert | Assist | Progress | Ended | Error | Ping,
    Field(discriminator="t"),
]
WsMessage = C2s | S2c

C2S_TYPES: tuple[str, ...] = (
    "hello",
    "resume",
    "text_utterance",
    "ask",
    "assist_request",
    "mark_met",
    "mark_waived",
    "acknowledge",
    "end",
    "pong",
)
S2C_TYPES: tuple[str, ...] = (
    "ready",
    "partial",
    "utterance",
    "verdict",
    "alert",
    "assist",
    "progress",
    "ended",
    "error",
    "ping",
)

c2s_adapter: TypeAdapter[Any] = TypeAdapter(C2s)
s2c_adapter: TypeAdapter[Any] = TypeAdapter(S2c)
