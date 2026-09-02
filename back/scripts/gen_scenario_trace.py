#!/usr/bin/env python3
"""시연 대본(script.json)에서 이벤트 trace 를 만든다.

왜 있나
    `contracts/fixtures/events_scenario_a.json` 은 trace 재생·리포트·접기 테스트의 원본인데
    손으로 옮겨 적어 왔다. 대본이 바뀌면 31건을 다시 손으로 맞춰야 하고, 실제로 2026-09-03
    까지 대본과 다른 문장·옛 원천 숫자(0.10%)를 담은 채 남아 있었다. 대본 한 파일을
    진실 원천으로 두고 여기서 이벤트를 다시 만든다.

무엇을 하나
    대본의 줄을 서버와 같은 문장 분리(`assembler.utterances`)로 나눠 실제 엔진
    (L0 → L1 → L2, 실물 임베더)에 순서대로 넣고, 나온 판정·경보·조력을 서버와 같은
    본문 매핑(`payload_to_event`)으로 이벤트에 담는다. L3(LLM) 몫인 판정·넛지와 카드
    채택(`outcome=adopted`)은 실행하지 않고, 대본 줄의 `l3` 주석대로 만들어 넣는다.
    종료 요약은 만든 이벤트를 다시 접어(`engine.fold`) 계산하므로 접기 테스트와 어긋날
    수 없다.

`l3` 주석 형식 (줄마다 배열)
    {"verdict": {"item_code", "axis", "state", "missing_elements"?}}
        L3 판정. 같은 항목·축의 앞 판정을 supersede
    {"nudge": "<item_code>"}
        빠진 요소 넛지(missing_item)
    {"adopt": {"assist_type": "rephrase" | "nudge", "item_code"}}
        앞 조력 카드를 outcome=adopted 로 다시 발행

사용
    cd back
    uv run python scripts/gen_scenario_trace.py ../assets/scenarios/preset-dep-a/script.json \
        --out contracts/fixtures/events_scenario_a.json
    이어서 `uv run python contracts/validate.py` 로 3층 검증.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACK))

from contracts.engine_contract import (  # noqa: E402
    AssistPayload,
    JudgeResult,
    Utterance,
    VerdictPayload,
)
from engine.adapters.embedder.local import LocalStEmbedder  # noqa: E402
from engine.adapters.pack_source.file import FilePackSource  # noqa: E402
from engine.adapters.vector_index.memory import MemoryVectorIndex  # noqa: E402
from engine.assist.nudge import nudge  # noqa: E402
from engine.build import build_engine  # noqa: E402
from server.mapping import payload_to_event  # noqa: E402
from server.services.session import chains  # noqa: E402
from server.services.stt.assembler import utterances as split_sentences  # noqa: E402

FIXTURES = BACK / "contracts" / "fixtures"
MS_PER_CHAR = 90  # 발화 길이 추정. TTS 실측이 나오면 대본의 duration 으로 바꾼다
STT_CONFIDENCE = 0.93
SPEAKER_CONFIDENCE = 0.97
L3_CONFIDENCE = 0.9


def _strip_none(value):
    """None 값을 재귀로 뺀다. 계약 스키마는 `comparison.condition` 같은 선택 필드에 null 을 허용하지
    않는다. 서버의 `payload_to_event._drop_none` 은 한 겹만 벗기므로 여기서 한 번 더."""
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
    return value


class Trace:
    """이벤트를 쌓으며 갱신 사슬(supersedes)을 잇는다.

    "이 항목·이 조력을 마지막으로 낸 게 어느 이벤트인가" 는 서버가 재접속 복구에도
    쓰는 `server.services.session.chains` 로 매번 다시 구한다. 여기서 따로 상태를
    들고 다니면, chains 의 키 모양이나 갱신 규칙이 나중에 바뀔 때 이 생성기만
    조용히 옛 규칙으로 남을 수 있다 — trace 재생이 실제 세션과 같은 `ver` 을 내야
    한다는 chains 자신의 존재 이유(모듈 docstring)를 이 파일도 그대로 따른다.
    """

    def __init__(self, session_id: str, pack_version: str, prefix: str, base: datetime) -> None:
        self.session_id = session_id
        self.pack_version = pack_version
        self.prefix = prefix
        self.base = base
        self.events: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self._clock_ms = 0

    def next_id(self) -> str:
        return f"{self.prefix}{len(self.events):04d}"

    def at(self, t_ms: int) -> None:
        self._clock_ms = t_ms

    def add(self, kind: str, body: dict, supersedes: str | None = None) -> dict:
        # 같은 시점에서 나온 파생 이벤트는 15ms 씩 뒤로 미룬다. 순서가 시각으로도 보이게
        self._clock_ms += 0 if kind == "utterance" else 15
        event = {
            "schema_version": "1",
            "event_id": self.next_id(),
            "session_id": self.session_id,
            "seq_in_session": len(self.events),
            "occurred_at": (self.base + timedelta(milliseconds=self._clock_ms)).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3]
            + "Z",
            "pack_version": self.pack_version,
            "kind": kind,
        }
        if supersedes:
            event["supersedes"] = supersedes
        event[kind] = _strip_none(body)
        self.events.append(event)
        self.by_id[event["event_id"]] = event
        return event

    def add_result(self, result: JudgeResult) -> None:
        latest_verdict = chains.latest_verdicts(self.events)
        for v in result.verdicts:
            key = (v.item_code, v.axis)
            ev = self.add("verdict", payload_to_event.verdict_body(v), latest_verdict.get(key))
            latest_verdict[key] = ev["event_id"]
        for a in result.alerts:
            self.add("alert", payload_to_event.alert_body(a))
        for s in result.assists:
            self.add_assist(s)

    def add_assist(self, s: AssistPayload) -> dict:
        """조력을 처음 제시한다. 이미 낸 것을 다시 낼 때는 `republish_assist` 를 쓴다."""
        return self.add("assist", payload_to_event.assist_body(s))

    def republish_assist(self, key: chains.AssistKey, updates: dict) -> dict | None:
        """이미 낸 조력을 새 필드로 다시 낸다(예: 채택 기록). 이전 발행을 supersede.

        낼 것이 없으면(그 조력이 아직 안 나왔으면) None."""
        latest = chains.latest_assists(self.events).get(key)
        if latest is None:
            return None
        prev_id, _ = latest
        body = {**self.by_id[prev_id]["assist"], **updates}
        return self.add("assist", body, prev_id)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("script", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--session-id", default="FIXT-SESS-0A")
    ap.add_argument("--id-prefix", default="FIXT-EV-")
    ap.add_argument("--base-time", default="2026-09-07T11:02:00Z")
    ap.add_argument("--pack-dir", type=Path, default=FIXTURES)
    a = ap.parse_args()

    script = json.loads(a.script.read_text(encoding="utf-8"))
    source = FilePackSource(a.pack_dir)
    engine = build_engine(source, LocalStEmbedder(), MemoryVectorIndex())
    pack = engine.load_pack(script["pack_version"])
    raw_pack = source.read(script["pack_version"])
    profile = script.get("customer_profile", {"type": "general", "tags": []})
    state = engine.initial_state(a.session_id, pack, script["mode"], profile["type"])
    base = datetime.fromisoformat(a.base_time.replace("Z", "+00:00")).astimezone(UTC)
    trace = Trace(a.session_id, pack.pack_version, a.id_prefix, base)

    trace.add(
        "session_started",
        {
            "mode": script["mode"],
            "product": raw_pack["product"],
            "customer_profile": profile,
            "item_count": len(pack.required_items()),
            "preset_id": script["preset_id"],
        },
    )

    for line in script["lines"]:
        t_ms = line["start_ms"]
        last_utt: str | None = None
        for sentence in split_sentences(line["text"]):
            trace.at(t_ms)
            utt_id = trace.next_id()
            utt = Utterance(
                utterance_id=utt_id,
                speaker=line["speaker"],
                text=sentence,
                t_ms=t_ms,
                duration_ms=len(sentence) * MS_PER_CHAR,
                stt_confidence=STT_CONFIDENCE,
                speaker_confidence=SPEAKER_CONFIDENCE,
            )
            trace.add("utterance", payload_to_event.utterance_body(utt))
            last_utt = utt_id
            result = engine.judge(utt, pack, state)
            state = engine.apply(state, result)
            trace.add_result(result)
            t_ms += utt.duration_ms + 400
        for note in line.get("l3", []):
            if "verdict" in note:
                spec = note["verdict"]
                item = pack.item(spec["item_code"])
                v = VerdictPayload(
                    item_code=spec["item_code"],
                    axis=spec["axis"],
                    state=spec["state"],
                    decided_by="L3",
                    confidence=L3_CONFIDENCE,
                    missing_elements=tuple(spec.get("missing_elements", ())),
                    utterance_ref=last_utt,
                    evidence=item.evidence if item else None,
                )
                result = JudgeResult(verdicts=(v,))
                state = engine.apply(state, result)
                trace.add_result(result)
            elif "nudge" in note:
                item = pack.item(note["nudge"])
                if item is None:
                    raise SystemExit(f"{line['id']}: 팩에 없는 item_code {note['nudge']!r}")
                cur = state.state_of(note["nudge"], "omission")
                missing = tuple(cur.missing_elements) if cur else ()
                trace.add_assist(nudge(item, missing, last_utt))
            elif "adopt" in note:
                spec = note["adopt"]
                key = chains.assist_key(spec)
                if trace.republish_assist(key, {"outcome": "adopted"}) is None:
                    raise SystemExit(f"{line['id']}: 채택할 조력이 없음 {key}")

    folded = engine.fold(trace.events)
    trace.at(script["duration_ms"])
    trace.add(
        "session_ended",
        {
            "reason": "normal",
            "duration_ms": script["duration_ms"],
            "summary": engine.summarize(folded, pack, trace.events),
        },
    )
    a.out.write_text(
        json.dumps(trace.events, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"events": len(trace.events), **trace.events[-1]["session_ended"]["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
