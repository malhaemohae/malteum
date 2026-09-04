"""전사 조립. 문장 분리와 PII 마스킹만 한다.

`server/AGENTS.md`: "프레임 조립·partial/final·문장 분리·PII 마스킹만. **의미 교정은
하지 않는다**(교정은 engine judge/refine)." 그래서 여기서 낱말을 고치거나 용어를
바로잡지 않는다 — 그건 L0 정규화(engine)가 팩 용어 사전으로 한다.

**왜 마스킹이 여기냐.** 확정 발화는 `session_events` 에 영구 저장되고 그것이 증빙의
정본이다. 한 번 들어간 계좌번호는 append-only 라 지울 수 없다. 저장 경로에 들어가기
전, 즉 전사를 발화로 바꾸는 이 지점이 마지막 관문이다.
"""

from __future__ import annotations

import re

MASK = "○○○"

# 상담 중 실제로 불릴 수 있는 것만. 넓게 잡으면 금액·이자율까지 지워져 ⑤ 숫자 오류
# 감지가 대조할 값을 잃는다 — 마스킹이 판정을 망치면 안 된다
_PII = (
    # 주민등록번호. 앞 6자리만 남기고 뒤를 가린다
    (re.compile(r"\b(\d{6})[-\s]?\d{7}\b"), r"\1-" + MASK),
    # 계좌번호. 은행마다 자릿수가 달라 하이픈으로 끊긴 10자리 이상을 본다
    (re.compile(r"\b\d{2,6}[-\s]\d{2,6}[-\s]\d{2,7}\b"), MASK),
    # 휴대전화
    (re.compile(r"\b01[016789][-\s]?\d{3,4}[-\s]?\d{4}\b"), MASK),
    # 카드번호 16자리
    (re.compile(r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b"), MASK),
)

# 문장 끝. Deepgram 이 punctuate 를 켜면 마침표가 붙어 온다
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def mask_pii(text: str) -> str:
    """계좌·주민·전화·카드 번호를 가린다. 금액과 이자율은 건드리지 않는다."""
    for pattern, repl in _PII:
        text = pattern.sub(repl, text)
    return text


def split_sentences(text: str) -> list[str]:
    """확정 전사 한 조각에 문장이 여럿일 수 있다. 판정은 문장 단위가 자연스럽다.

    쪼개지 않으면 "우대이자율은 안 됩니다. 0.5% 받으세요." 가 한 발화가 되어, 정상 고지와
    숫자 오류가 같은 판정 대상에 섞인다.
    """
    parts = [s.strip() for s in _SENTENCE.split(text.strip()) if s.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def utterances(text: str) -> list[str]:
    """전사 → 저장 가능한 발화들. 마스킹을 먼저 하고 나눈다."""
    return split_sentences(mask_pii(text))
