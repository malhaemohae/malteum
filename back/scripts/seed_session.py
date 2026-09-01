#!/usr/bin/env python3
"""계약 fixture 의 세션 이벤트를 postgres 에 적재한다 (trace 재생용).

왜 필요한가
    `trace` 는 저장된 이벤트를 타임스탬프대로 다시 흘린다(11.4). 재생할 원본이 DB 에
    없으면 심사 기본 경로의 재현성 증명이 통째로 빠진다. 그 원본을 넣는 재현 가능한
    경로가 지금까지 없어서, 팩이 재발행될 때마다 손으로 다시 넣어야 했다.

왜 계약 fixture 인가
    `contracts/fixtures/` 가 계약 테스트 그 자체다(`contracts/README.md`). 시연용
    데이터를 따로 만들면 팩이 바뀔 때 조용히 어긋난다. 실제로 2026-08-30 팩 재발행에서
    항목 코드 3건이 바뀌었고, 그때 DB 에 남아 있던 옛 이벤트는 없는 코드를 가리켰다.

왜 M1 의 저장소를 그대로 쓰는가
    봉투 모양을 SQL 로 다시 적으면 계약이 늘 때 이 파일만 뒤처진다. `scripts/` 는
    import-linter 의 `root_packages` 밖이라 이 import 는 경계를 어기지 않는다
    (`scripts/load_pack.py` 와 같은 판단).

멱등성
    같은 세션을 두 번 넣으면 `uq_session_events_seq` 에 걸린다. 이미 있으면 기본적으로
    거절하고 `--replace` 를 주면 지운 뒤 다시 넣는다.

사용
    uv run python scripts/seed_session.py                       # events_scenario_a.json
    uv run python scripts/seed_session.py --replace
    uv run python scripts/seed_session.py path/to/events.json
    APP_DATABASE_URL 로 접속 대상을 준다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 한국어 Windows 는 stdout 이 cp949 라 한글·기호가 깨진다 (scripts/smoke.py 와 같은 처리)
sys.stdout.reconfigure(encoding="utf-8")

BACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACK))

from sqlalchemy import delete  # noqa: E402

from server.bootstrap.settings import get_settings  # noqa: E402
from server.database.entities import Session as SessionRow  # noqa: E402
from server.database.entities import SessionEvent  # noqa: E402
from server.database.session import make_sessions  # noqa: E402
from server.generated import events as gen  # noqa: E402
from server.services.event.store import PostgresEventStore  # noqa: E402
from server.services.session.projection import PostgresSessionProjection  # noqa: E402

DEFAULT = BACK / "contracts" / "fixtures" / "events_scenario_a.json"


def load(path: Path) -> list[dict]:
    """스키마를 통과한 이벤트만 넣는다. 계약을 어긴 원본이 DB 에 들어가면
    재생·리포트가 그것을 그대로 믿는다."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"이벤트 배열이 아닙니다: {path}")
    for event in raw:
        gen.event_adapter.validate_python(event)
    return sorted(raw, key=lambda e: e["seq_in_session"])


def main() -> int:
    ap = argparse.ArgumentParser(description="세션 이벤트 fixture 를 postgres 에 적재")
    ap.add_argument("path", nargs="?", default=str(DEFAULT), help="이벤트 배열 JSON")
    ap.add_argument("--replace", action="store_true", help="이미 있으면 지우고 다시 넣음")
    ap.add_argument("--dry-run", action="store_true", help="검증만 하고 넣지 않음")
    args = ap.parse_args()

    path = Path(args.path)
    if not path.is_absolute():
        path = (BACK / path).resolve() if not path.exists() else path.resolve()
    events = load(path)
    session_ids = {e["session_id"] for e in events}
    if len(session_ids) != 1:
        raise SystemExit(f"한 세션이어야 합니다: {sorted(session_ids)}")
    session_id = session_ids.pop()
    kinds = {}
    for e in events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print(f"{path.name}: {session_id} · {len(events)}건 · {kinds}")

    if args.dry_run:
        print("dry-run: 넣지 않음")
        return 0

    settings = get_settings()
    sessions = make_sessions(settings.database_url)
    store = PostgresEventStore(sessions)
    projection = PostgresSessionProjection(sessions)

    if store.of_session(session_id):
        if not args.replace:
            raise SystemExit(f"이미 있습니다: {session_id} (--replace 로 덮어씀)")
        with sessions.begin() as db:
            db.execute(delete(SessionEvent).where(SessionEvent.session_id == session_id))
            db.execute(delete(SessionRow).where(SessionRow.session_id == session_id))
        print(f"지움: {session_id}")

    store.append_many(events)
    # sessions 는 이벤트를 접어 만든 파생 투영이다. 목록 화면(S5)이 이것을 읽는다
    for e in events:
        if e["kind"] == "session_started":
            projection.opened(e)
        elif e["kind"] == "session_ended":
            projection.ended(e)
    print(f"적재: {session_id} · {len(events)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
