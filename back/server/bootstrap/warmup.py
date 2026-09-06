"""부팅 직후 판정 엔진을 데운다. 첫 상담이 모델 로딩을 기다리지 않게 하는 자리다.

임베딩 모델은 처음 쓸 때 읽힌다(`engine/adapters/embedder/local.py` 의 지연 로딩).
그 첫 사용이 상담을 여는 순간에 걸리면 `registry.open` 이 동기라 **이벤트 루프 전체가**
그동안 멈춘다. 하트비트도, 다른 상담도, `/health` 도 함께 멈춘다.

실측(2026-09-06, Windows CPU): sentence-transformers import 21.8초 + 모델 로드 4.5초 +
첫 인코딩 0.3초 = 26.5초. 두 번째 인코딩부터는 11ms 다. 서버가 뜬 뒤 사람이 화면을 열고
팩을 고르는 사이에 이 26초를 미리 치러 두면 첫 상담이 곧바로 시작된다.

**서버 기동을 막지 않는다.** lifespan 이 이것을 기다리면 그동안 `/health` 가 응답하지
않아 컨테이너가 unhealthy 로 뜬다. 배경 태스크로 돌리고 상태만 남긴다.

**실패해도 서버는 산다.** 모델을 못 읽으면 L2 가 빠진 채로 도는 것이 기존 동작이고
(`engine.judge` 의 [DUMMY] 경고), 워밍업 실패가 그 폴백을 막을 이유가 없다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Warmup:
    """워밍업 진행 상태. `/health` 의 `checks.embedding` 이 이것을 읽는다."""

    ready: bool = False
    error: str | None = None
    elapsed_s: float = 0.0
    versions: tuple[str, ...] = field(default_factory=tuple)


def _versions(runtime, settings) -> list[str]:
    """데울 팩. 상품별 최신만. 화면이 고를 수 있는 것과 같은 집합이다.

    목록 조회가 실패하면 기본 팩 하나로 물러선다. 하나라도 데우면 모델은 올라오고,
    나머지 팩은 첫 사용에 항목 수만큼만(십여 개) 인코딩하면 된다.
    """
    try:
        rows = runtime.pack_store.list(None, True)
        found = [str(r["pack_version"]) for r in rows if r.get("pack_version")]
        if found:
            return found
    except Exception as e:  # noqa: BLE001  목록이 없어도 기본 팩은 데운다
        log.warning("워밍업 대상 팩 목록을 읽지 못했습니다: %s: %s", type(e).__name__, e)
    return [settings.default_pack_version]


def _load(runtime, settings, state: Warmup) -> None:
    """스레드에서 도는 실제 작업. 팩 로드가 임베딩 모델과 인덱스까지 함께 올린다."""
    started = time.perf_counter()
    done: list[str] = []
    for version in _versions(runtime, settings):
        try:
            runtime.registry.pack(version)  # engine.load_pack → compile → index.add_pack
            done.append(version)
        except Exception as e:  # noqa: BLE001  한 팩이 깨져도 나머지는 데운다
            state.error = f"{version}: {type(e).__name__}: {e}"
            log.warning("규정 팩 워밍업 실패 (%s): %s: %s", version, type(e).__name__, e)
    state.versions = tuple(done)
    state.elapsed_s = round(time.perf_counter() - started, 3)
    state.ready = bool(done)


async def warm(runtime, settings) -> None:
    """배경 태스크 하나. 끝나면 상태만 남기고 조용히 종료한다."""
    state: Warmup = runtime.warmup
    try:
        await asyncio.to_thread(_load, runtime, settings, state)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001  워밍업 실패가 서버를 내리지 않게 한다
        state.error = f"{type(e).__name__}: {e}"
        log.warning("판정 엔진 워밍업 실패: %s: %s", type(e).__name__, e)
        return
    if state.ready:
        log.info("판정 엔진 준비 완료: %s (%.1f초)", ", ".join(state.versions), state.elapsed_s)
