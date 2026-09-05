"""끝까지 언급되지 않은 필수 항목(판정 이벤트 없음)이 화면·리포트에서 사라지지 않는다.

시연 대본 A 는 DEP-LIM-001 을 한 번도 말하지 않는다. 종료 요약은 그것을 unmet 으로
세는데(summary.py), progress 의 남은 목록과 리포트의 미고지 표가 상태에 있는 항목만
돌면 그 항목이 조용히 빠져 요약의 unmet 수와 어긋난다(2026-09-04 E2E 에서 발견).
"""

from __future__ import annotations

import json

from engine.adapters.pack_source.file import FilePackSource
from engine.build import build_engine
from server.bootstrap.settings import BACK_DIR
from server.mapping import event_to_s2c
from server.services import report

FIXTURES = BACK_DIR / "contracts" / "fixtures"


def _engine_and_events():
    engine = build_engine(FilePackSource(FIXTURES))
    events = json.loads((FIXTURES / "events_scenario_a.json").read_text(encoding="utf-8"))
    pack = engine.load_pack(events[0]["pack_version"])
    return engine, pack, events


def test_progress_lists_never_mentioned_required_items_as_remaining():
    engine, pack, events = _engine_and_events()
    state = engine.fold([e for e in events if e["kind"] == "session_started"])
    fresh = event_to_s2c.progress(pack, state)
    assert set(fresh["remaining"]) == {it.name for it in pack.required_items()}

    final = event_to_s2c.progress(pack, engine.fold(events))
    lim = next(it.name for it in pack.required_items() if it.code == "DEP-LIM-001")
    assert lim in final["remaining"]


def test_report_omission_rows_cover_every_required_item():
    engine, pack, events = _engine_and_events()
    built = report.build("FIXT-SESS-UNMET", events, engine, pack, doc=None)
    rows = {r["item_code"]: r for r in built["sections"]["omission"]}
    assert set(rows) >= {it.code for it in pack.required_items()}
    assert rows["DEP-LIM-001"]["state"] == "unmet" and rows["DEP-LIM-001"]["decided_by"] is None
    summary = built["sections"]["summary"]
    assert sum(1 for r in rows.values() if r["state"] == "unmet") == summary["unmet"]


def test_report_commission_rows_include_number_and_forbidden_alerts():
    """숫자 오류·금지 표현 경보는 항목 상태(violated)와 별개로 나므로 표에 행으로 남아야 한다.

    2026-09-06 실측: 숫자 경보 2건인 상담의 금지·숫자 표가 비어 있었다. 기획 §10 은
    "리포트에 위반 1건" 을 기대한다.
    """
    engine, pack, events = _engine_and_events()
    built = report.build("FIXT-SESS-ALERTS", events, engine, pack, doc=None)
    rows = built["sections"]["commission"]
    alerts = [r for r in rows if r.get("kind") == "alert"]
    expected = [
        e
        for e in events
        if e["kind"] == "alert" and e["alert"]["alert_type"] in report.COMMISSION_ALERTS
    ]
    superseded = {e["supersedes"] for e in events if e.get("supersedes")}
    assert len(alerts) == len([e for e in expected if e["event_id"] not in superseded])
    assert all("message" in r and "acknowledged" in r and "t_ms" in r for r in alerts)
    assert not any(r.get("alert_type") == "risk_signal" for r in alerts)
    # 항목 상태 행은 그대로 남아 있다
    assert all("state" in r for r in rows if r.get("kind") != "alert")
