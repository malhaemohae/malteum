"""프레임 간격 분포 (`ws/pacing.py`).

유휴 닫기 임계값(`stt_idle_flush_ms`)이 지금은 산술로 잡은 값이다. 실제 상담 하나의
간격 분포를 봐야 실측으로 바꿀 수 있고, 그러려면 재는 쪽이 먼저 맞아야 한다.
"""

from __future__ import annotations

from server.ws.pacing import FramePacing


def test_the_first_frame_makes_no_gap():
    """앞이 없는 프레임으로 0ms 간격을 만들면 분포가 0 쪽으로 밀린다."""
    pacing = FramePacing()
    pacing.saw_frame(now=10.0)
    assert pacing.total == 0
    assert pacing.summary() == "오디오 프레임 없음"


def test_bursts_of_frames_read_as_the_gap_between_bursts():
    """브라우저는 프레임을 묶어 보낸다. 묶음 안은 0ms, 묶음 사이가 실제 간격이다."""
    pacing = FramePacing()
    at = 0.0
    for _ in range(4):  # 256ms 마다 세 개씩 (16kHz 버퍼 4096 샘플)
        for _ in range(3):
            pacing.saw_frame(now=at)
            at += 0.001
        at += 0.253
    assert pacing.total == 11
    # 묶음 사이 세 번만 250ms 를 넘는다. 나머지는 묶음 안이다
    assert pacing.max_ms > 250
    assert pacing.quantile_ms(0.5) == 50.0


def test_a_long_stop_lands_in_the_last_bucket_and_keeps_the_real_maximum():
    """녹음 중지는 마지막 칸에 걸린다. 칸에는 상한이 없으므로 실제 최댓값을 따로 든다."""
    pacing = FramePacing()
    pacing.saw_frame(now=0.0)
    pacing.saw_frame(now=0.1)
    pacing.saw_frame(now=40.0)  # 마이크를 끄고 40초 뒤 재개
    assert pacing.counts[-1] == 1
    assert pacing.max_ms > 39_000
    assert pacing.quantile_ms(0.99) == pacing.max_ms
    assert "최대 39900ms" in pacing.summary()


def test_the_summary_carries_every_bucket():
    """어느 칸이 비었는지도 정보다. 빈 칸을 빼면 분포가 아니라 요약이 된다."""
    pacing = FramePacing()
    at = 0.0
    for step in (0.02, 0.26, 0.9, 1.8):
        pacing.saw_frame(now=at)
        at += step
    pacing.saw_frame(now=at)
    summary = pacing.summary()
    assert summary.count(":") == 10  # 경계 9개 + 상한 없는 마지막 칸
    assert "<50ms:1" in summary and "<400ms:1" in summary and "<2000ms:1" in summary
