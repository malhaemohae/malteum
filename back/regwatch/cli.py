from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from .config import ConfigError, load_sources
from .engine import StateError, run_monitor
from .fetcher import HttpFetcher


def _root() -> Path:
    # flat 배치(back/regwatch/)에서 regwatch 홈은 이 파일의 폴더다
    return Path(__file__).resolve().parent


def _parser() -> argparse.ArgumentParser:
    root = _root()
    parser = argparse.ArgumentParser(prog="malteum-regwatch")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="공식 원천을 조회하고 이전 상태와 비교함")
    run.add_argument("--config", type=Path, default=root / "config" / "sources.json")
    run.add_argument("--state", type=Path, default=root / "var" / "state.json")
    run.add_argument("--report", type=Path, default=root / "var" / "latest-report.json")
    run.add_argument("--timeout", type=float, default=30.0)
    return parser


def _operational_error(report_path: Path, error: Exception) -> int:
    print(
        json.dumps(
            {
                "checked_at": None,
                "has_errors": True,
                "affected_products": [],
                "summary": {"baseline": 0, "unchanged": 0, "changed": 0, "error": 1},
                "error": str(error),
                "report": str(report_path.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2


def main(argv: Sequence[str] | None = None, *, fetcher=None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "run":
        raise AssertionError(f"지원하지 않는 명령: {args.command}")

    try:
        sources = load_sources(args.config)
        result = run_monitor(
            sources,
            fetcher or HttpFetcher(timeout_seconds=args.timeout),
            args.state,
            args.report,
        )
    except (ConfigError, StateError) as exc:
        return _operational_error(args.report, exc)
    counts = Counter(item.status for item in result.sources)
    print(
        json.dumps(
            {
                "checked_at": result.checked_at,
                "has_errors": result.has_errors,
                "affected_products": sorted(result.affected_products),
                "summary": {
                    status: counts.get(status, 0)
                    for status in ("baseline", "unchanged", "changed", "error")
                },
                "report": str(args.report.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if result.has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
