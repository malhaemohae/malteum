"""engine 이 밖으로 던지는 예외와 경고. 더미 경로는 전부 DummyPathWarning 으로 남긴다."""

from __future__ import annotations

import logging
import warnings

log = logging.getLogger("engine")


class BudgetExceeded(RuntimeError):
    """지연 예산 초과. refine 에서는 잠정 판정 유지로 흡수한다."""


class DummyPathWarning(UserWarning):
    """더미·임시 데이터가 쓰인 경로. 운영 로그에서 [DUMMY] 로 검색된다."""


def warn_dummy(message: str) -> None:
    text = f"[DUMMY] {message}"
    log.warning(text)
    warnings.warn(text, DummyPathWarning, stacklevel=2)
