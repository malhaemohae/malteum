"""오디오 프레임이 실제로 얼마 간격으로 도착하는가.

유휴 닫기의 임계값(`stt_idle_flush_ms`)은 "정상 도착 간격의 꼬리"보다 넉넉해야 한다.
짧으면 회선이 잠깐 튄 것을 녹음 중지로 오해해 말하는 중에 발화를 끊고, 길면 마지막
발화가 그만큼 늦게 나온다. 그 꼬리를 짐작으로 정하지 않으려고 여기서 잰다.

**프레임은 100ms 마다 하나씩 오지 않는다.** 프레임 하나가 담는 소리가 100ms 일 뿐이고,
브라우저는 Web Audio 의 버퍼 콜백이 찰 때마다 여러 개를 몰아 보낸다
(`front/lib/audio.ts` 의 `createScriptProcessor(4096, ...)`). 버퍼 4,096 샘플을
16kHz 로 잡으면 256ms 마다 두세 개가 붙어 나가고, 16kHz 로 못 잡아 기기 기본 속도
(흔히 48kHz)로 내려앉으면 약 85ms 마다 한 개 이하다. 즉 완벽한 회선에서도 묶음과
묶음 사이가 250ms 남짓 벌어진다. 여기에 회선 흔들림이 더 붙는다.

상담이 끝날 때 한 줄로 남긴다. 실제 상담 한 번이면 임계값을 추정이 아니라 실측으로
정할 수 있다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# 구간 경계(ms). 마지막 칸은 상한 없음. 250ms 언저리가 정상 묶음 간격이라 그 앞뒤를
# 촘촘히 두고, 유휴 임계값 후보 구간(1~2초)도 따로 볼 수 있게 갈랐다
BUCKETS_MS = (50.0, 150.0, 250.0, 400.0, 600.0, 1000.0, 1500.0, 2000.0, 3000.0)


@dataclass
class FramePacing:
    """프레임 사이 간격의 분포. 값을 다 들고 있지 않고 칸으로만 센다.

    30분 상담이면 프레임이 1만 8천 개다. 간격을 통째로 들고 있을 이유가 없고, 알고 싶은
    것은 "몇 ms 를 넘는 일이 얼마나 잦은가" 하나뿐이라 칸으로 세면 메모리가 상수다.
    """

    counts: list[int] = field(default_factory=lambda: [0] * (len(BUCKETS_MS) + 1))
    max_ms: float = 0.0
    total: int = 0
    _last_at: float | None = None

    def saw_frame(self, now: float | None = None) -> None:
        """프레임 하나가 도착했다. 첫 프레임은 앞이 없어 간격을 만들지 않는다."""
        at = time.monotonic() if now is None else now
        last, self._last_at = self._last_at, at
        if last is None:
            return
        gap_ms = (at - last) * 1000
        self.total += 1
        self.max_ms = max(self.max_ms, gap_ms)
        for index, edge in enumerate(BUCKETS_MS):
            if gap_ms < edge:
                self.counts[index] += 1
                return
        self.counts[-1] += 1

    def quantile_ms(self, share: float) -> float:
        """이 비율까지 덮는 칸의 위쪽 경계. 칸으로만 세므로 정확한 값이 아니라 상한이다.

        `0.99` 를 물으면 "간격의 99 %가 이 값 미만" 이라고 읽는다. 마지막 칸에 걸리면
        상한이 없으므로 실제로 본 최댓값을 돌려준다.
        """
        if self.total == 0:
            return 0.0
        target, seen = share * self.total, 0
        for index, count in enumerate(self.counts):
            seen += count
            if seen >= target:
                return BUCKETS_MS[index] if index < len(BUCKETS_MS) else self.max_ms
        return self.max_ms

    def summary(self) -> str:
        """로그 한 줄. 칸별 개수와 꼬리를 함께 낸다."""
        if self.total == 0:
            return "오디오 프레임 없음"
        paired = zip(BUCKETS_MS, self.counts[:-1], strict=True)
        edges = [f"<{int(edge)}ms:{count}" for edge, count in paired]
        edges.append(f">={int(BUCKETS_MS[-1])}ms:{self.counts[-1]}")
        return (
            f"프레임 간격 {self.total}건, 최대 {self.max_ms:.0f}ms, "
            f"p99 {self.quantile_ms(0.99):.0f}ms 미만 · " + " ".join(edges)
        )
