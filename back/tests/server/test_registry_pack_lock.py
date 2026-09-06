"""팩 적재는 여러 스레드가 동시에 불러도 한 번만 일어난다.

예열(`bootstrap/warmup.py`)이 배경 스레드에서 돌기 시작하면서 같은 팩을 두 곳에서
처음 부르는 일이 생겼다. 예열 스레드와 상담 요청(`POST /sessions` 는 동기 함수라
FastAPI 가 워커 스레드에서 돌린다)이다. 검사와 대입 사이가 벌어지면 임베딩 모델이
두 벌 올라가고, 실측에서 두 스레드가 동시에 `SentenceTransformer` 를 만들다
`NotImplementedError: Cannot copy out of meta tensor` 로 함께 죽은 적이 있다.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from server.services.session.registry import SessionRegistry


class _SlowEngine:
    """팩 적재가 느린 엔진. 적재 횟수와 동시 진입 최대치를 센다."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.calls: list[str] = []
        self.inside = 0
        self.peak = 0
        self._count_lock = threading.Lock()

    def load_pack(self, pack_version: str):
        with self._count_lock:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
            self.calls.append(pack_version)
        time.sleep(self.delay)
        with self._count_lock:
            self.inside -= 1
        return SimpleNamespace(pack_version=pack_version)


def _run(registry: SessionRegistry, versions: list[str]) -> list:
    results: list = [None] * len(versions)
    ready = threading.Barrier(len(versions))

    def call(index: int) -> None:
        ready.wait()
        results[index] = registry.pack(versions[index])

    threads = [threading.Thread(target=call, args=(i,)) for i in range(len(versions))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_same_pack_is_loaded_once_even_when_four_threads_race() -> None:
    engine = _SlowEngine()
    registry = SessionRegistry(engine, store=None)  # type: ignore[arg-type]

    results = _run(registry, ["DEP-2026.08-v6"] * 4)

    assert engine.calls == ["DEP-2026.08-v6"], engine.calls
    # 네 스레드가 같은 객체를 받는다. 늦게 온 쪽이 앞의 적재 결과를 기다렸다는 뜻이다
    assert len({id(value) for value in results}) == 1


def test_different_packs_do_not_load_at_the_same_time() -> None:
    """다른 팩이어도 겹치면 모델이 두 벌 올라간다. 잠금이 그것을 막는다."""
    engine = _SlowEngine()
    registry = SessionRegistry(engine, store=None)  # type: ignore[arg-type]

    _run(registry, ["DEP-2026.08-v6", "LOAN-2026.08-v7"])

    assert sorted(engine.calls) == ["DEP-2026.08-v6", "LOAN-2026.08-v7"]
    assert engine.peak == 1, f"동시에 {engine.peak} 벌이 적재됐다"


def test_cached_pack_returns_without_taking_the_lock() -> None:
    """두 번째 호출부터는 적재도 대기도 없다. 잠금이 매 판정 경로를 느리게 하지 않는다."""
    engine = _SlowEngine(delay=0.2)
    registry = SessionRegistry(engine, store=None)  # type: ignore[arg-type]
    first = registry.pack("DEP-2026.08-v6")

    started = time.perf_counter()
    again = registry.pack("DEP-2026.08-v6")
    elapsed = time.perf_counter() - started

    assert again is first
    assert len(engine.calls) == 1
    assert elapsed < 0.05, elapsed
