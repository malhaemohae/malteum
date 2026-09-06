"""Deterministic replay pacing with consumer work and the real event mapper/fold."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from engine.adapters.pack_source.file import FilePackSource
from engine.build import build_engine
from server.bootstrap.settings import BACK_DIR
from server.services.session import replay
from server.services.stt import audio


class Clock:
    def __init__(self):
        self.now = 500.0
        self.start = self.now
        self.sleeps = []

    def time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds

    async def sleep(self, seconds):
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.advance(seconds)

    @property
    def elapsed(self):
        return self.now - self.start


def install_clock(monkeypatch, module, clock):
    # Replace only this module's asyncio reference, not the test runner's loop.
    monkeypatch.setattr(
        module, "asyncio", SimpleNamespace(get_running_loop=lambda: clock, sleep=clock.sleep)
    )


@pytest.mark.parametrize("processing_s", [0.0, 0.025, 0.075])
def test_audio_consumer_work_does_not_accumulate_drift(monkeypatch, processing_s):
    clock = Clock()
    install_clock(monkeypatch, audio, clock)
    pcm = bytes(range(256)) * 1250  # Ten seconds of PCM16 at 16 kHz.
    frames, times = [], []

    async def consume():
        async for frame in audio.stream(pcm):
            frames.append(frame)
            times.append(clock.elapsed)
            clock.advance(processing_s)

    asyncio.run(consume())
    assert b"".join(frames) == pcm
    assert times == pytest.approx([i / 10 for i in range(100)])
    assert clock.elapsed == pytest.approx(10.0)


@pytest.mark.parametrize("samples", [0, 1, 800, 1600, 4000])
def test_audio_preserves_exact_duration_including_short_last_frame(monkeypatch, samples):
    clock = Clock()
    install_clock(monkeypatch, audio, clock)
    pcm = b"\x01\x02" * samples
    frames = []

    async def consume():
        async for frame in audio.stream(pcm):
            frames.append(frame)

    asyncio.run(consume())
    assert b"".join(frames) == pcm
    assert clock.elapsed == pytest.approx(samples / audio.SAMPLE_RATE)
    if not pcm:
        assert not frames and not clock.sleeps


def test_audio_overrun_keeps_every_frame_and_recovers_without_extra_delay(monkeypatch):
    clock = Clock()
    install_clock(monkeypatch, audio, clock)
    pcm = b"\x01\x02" * 8000
    frames, times = [], []
    processing = iter([0.25, 0.01, 0.01, 0.01, 0.01])

    async def consume():
        async for frame in audio.stream(pcm):
            frames.append(frame)
            times.append(clock.elapsed)
            clock.advance(next(processing))

    asyncio.run(consume())
    assert b"".join(frames) == pcm
    assert times == pytest.approx([0, 0.25, 0.26, 0.3, 0.4])
    assert clock.elapsed == pytest.approx(0.5)


def test_audio_sustained_overload_does_not_drop_or_add_sleeps(monkeypatch):
    clock = Clock()
    install_clock(monkeypatch, audio, clock)
    pcm = b"\x01\x02" * 4800
    frames = []

    async def consume():
        async for frame in audio.stream(pcm):
            frames.append(frame)
            clock.advance(0.2)

    asyncio.run(consume())
    assert b"".join(frames) == pcm
    assert clock.elapsed == pytest.approx(0.6)


@pytest.fixture
def trace_engine():
    return build_engine(FilePackSource(BACK_DIR / "contracts" / "fixtures"))


def trace_events(offsets):
    base = datetime(2026, 9, 6, tzinfo=UTC)
    events = []
    for i, offset in enumerate(offsets):
        kind = "session_started" if i == 0 else "utterance"
        body = (
            {"mode": "text", "customer_profile": {"type": "general"}}
            if i == 0
            else {"speaker": "teller", "text": f"발화 {i}", "t_ms": i * 1000}
        )
        events.append(
            {
                "event_id": f"EVENT-{i}",
                "seq_in_session": i,
                "session_id": "TIMING-SESSION",
                "pack_version": "DEP-2026.08-v6",
                "occurred_at": (base + timedelta(seconds=offset)).isoformat(),
                "kind": kind,
                kind: body,
            }
        )
    return events


def run_trace(monkeypatch, engine, events, *, fold_s=0.0, publish_s=0.0):
    clock = Clock()
    install_clock(monkeypatch, replay, clock)
    sent, folded = [], []

    def fold(prefix):
        clock.advance(fold_s)
        folded.append([e["event_id"] for e in prefix])
        return engine.fold(prefix)

    async def publish(message):
        sent.append((clock.elapsed, message))
        clock.advance(publish_s)

    pack = engine.load_pack("DEP-2026.08-v6")
    asyncio.run(replay.replay(SimpleNamespace(fold=fold), pack, events, publish))
    return clock, sent, folded


def test_trace_fold_and_publish_work_do_not_accumulate_or_shorten_long_gap(
    monkeypatch, trace_engine
):
    events = trace_events([0, 1, 2, 36.9, 37.9])
    original = deepcopy(events)
    clock, sent, folded = run_trace(
        monkeypatch, trace_engine, list(reversed(events)), fold_s=0.05, publish_s=0.2
    )
    assert [t for t, _ in sent] == pytest.approx([1.05, 2.05, 36.95, 37.95])
    assert clock.elapsed == pytest.approx(38.15)
    assert [m["event_id"] for _, m in sent] == [e["event_id"] for e in events[1:]]
    assert [m["t_ms"] for _, m in sent] == [1000, 2000, 3000, 4000]
    assert folded == [[e["event_id"] for e in events[:i]] for i in range(1, 6)]
    assert events == original


def test_trace_keeps_zero_and_negative_gap_semantics(monkeypatch, trace_engine):
    events = trace_events([0, 1, 1, 0.5, 2])
    _, sent, _ = run_trace(monkeypatch, trace_engine, events, publish_s=0.1)
    # Negative gaps remain zero; the final positive gap remains 1.5 seconds.
    assert [t for t, _ in sent] == pytest.approx([1, 1.1, 1.2, 2.5])
    assert [m["event_id"] for _, m in sent] == [e["event_id"] for e in events[1:]]


def test_trace_slow_consumer_preserves_order_without_adding_full_gap(monkeypatch, trace_engine):
    events = trace_events([0, 1, 2, 3])
    clock, sent, _ = run_trace(monkeypatch, trace_engine, events, publish_s=1.5)
    assert [t for t, _ in sent] == pytest.approx([1, 2.5, 4])
    assert clock.elapsed == pytest.approx(5.5)
    assert [m["event_id"] for _, m in sent] == [e["event_id"] for e in events[1:]]


def test_trace_verdict_progress_and_assist_versions_preserved(monkeypatch, trace_engine):
    events = trace_events([0, 1, 2, 3, 4, 5])
    for i, state in [(1, "partial"), (2, "met")]:
        del events[i]["utterance"]
        events[i].update(
            kind="verdict",
            verdict={
                "item_code": "DEP-INT-002",
                "axis": "omission",
                "state": state,
                "decided_by": "L1" if i == 1 else "L3",
            },
            supersedes=None if i == 1 else events[1]["event_id"],
        )
    for i in (3, 4):
        del events[i]["utterance"]
        events[i].update(
            kind="assist",
            assist={"assist_type": "rephrase", "text": "도움말", "item_code": "DEP-INT-002"},
            supersedes=None if i == 3 else events[3]["event_id"],
        )
    events[4]["assist"]["outcome"] = "adopted"
    original = deepcopy(events)
    _, sent, _ = run_trace(monkeypatch, trace_engine, events, publish_s=0.2)
    assert [m["t"] for _, m in sent] == [
        "verdict",
        "progress",
        "verdict",
        "progress",
        "assist",
        "assist",
        "utterance",
    ]
    assert [t for t, _ in sent] == pytest.approx([1, 1.2, 2, 2.2, 3, 4, 5])
    assert [m["ver"] for _, m in sent if m["t"] == "verdict"] == [1, 2]
    assert [m["ver"] for _, m in sent if m["t"] == "assist"] == [1, 2]
    assert sent[1][1]["partial"] == 1 and sent[3][1]["met"] == 1
    assert sent[5][1]["outcome"] == "adopted"
    assert events == original


def test_empty_trace_does_not_publish_or_sleep(monkeypatch, trace_engine):
    clock, sent, folded = run_trace(monkeypatch, trace_engine, [])
    assert sent == folded == clock.sleeps == []


def test_audio_scheduler_oversleep_does_not_accumulate(monkeypatch):
    class OversleepClock(Clock):
        async def sleep(self, seconds):
            await super().sleep(seconds)
            self.advance(0.005)

    clock = OversleepClock()
    install_clock(monkeypatch, audio, clock)
    times = []

    async def consume():
        async for _ in audio.stream(b"\x01\x02" * 16000):
            times.append(clock.elapsed)
            clock.advance(0.025)

    asyncio.run(consume())
    assert times == pytest.approx([0] + [i / 10 + 0.005 for i in range(1, 10)])
    assert clock.elapsed == pytest.approx(1.005)
