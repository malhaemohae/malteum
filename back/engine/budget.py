"""시간 측정. tiers 는 시간을 모르고, 여기서 감싸 TierTrace 를 만든다."""

from __future__ import annotations

import time
from contextlib import contextmanager


class Stopwatch:
    def __init__(self) -> None:
        self.ms: dict[str, float] = {}

    @contextmanager
    def lap(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.ms[name] = self.ms.get(name, 0.0) + (time.perf_counter() - t0) * 1000
