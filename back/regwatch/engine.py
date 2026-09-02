from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from .fetcher import FetchError
from .fingerprint import FingerprintError, fingerprint
from .models import RunReport, SourceOutcome, SourceSpec


class StateError(RuntimeError):
    """이전 감시 상태를 안전하게 읽거나 저장하지 못함."""


def _load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": 1, "sources": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"상태 파일을 읽지 못함: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), dict):
        raise StateError("상태 파일 구조가 잘못됨")
    return payload


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise StateError(f"JSON 파일을 원자적으로 저장하지 못함: {path}: {exc}") from exc


def _report_payload(report: RunReport) -> dict[str, object]:
    counts = Counter(item.status for item in report.sources)
    return {
        "schema_version": 1,
        "checked_at": report.checked_at,
        "has_errors": report.has_errors,
        "affected_products": sorted(report.affected_products),
        "summary": {
            status: counts.get(status, 0)
            for status in ("baseline", "unchanged", "changed", "error")
        },
        "sources": [
            {
                "source_id": item.source_id,
                "category": item.category,
                "title": item.title,
                "status": item.status,
                "impacts": sorted(item.impacts),
                "sha256": item.sha256,
                "previous_sha256": item.previous_sha256,
                "error": item.error,
            }
            for item in report.sources
        ],
    }


def run_monitor(
    sources: Iterable[SourceSpec],
    fetcher,
    state_path: Path,
    report_path: Path,
    *,
    now: Callable[[], datetime] | None = None,
) -> RunReport:
    checked_at = (now or (lambda: datetime.now(UTC)))().isoformat()
    state = _load_state(state_path)
    stored = state["sources"]
    assert isinstance(stored, dict)

    outcomes: list[SourceOutcome] = []
    affected: set[str] = set()
    for source in sources:
        previous = stored.get(source.source_id)
        previous_sha = previous.get("sha256") if isinstance(previous, dict) else None
        try:
            snapshot = fingerprint(source, fetcher.fetch(source))
        except (FetchError, FingerprintError) as exc:
            outcomes.append(
                SourceOutcome(
                    source_id=source.source_id,
                    category=source.category,
                    title=source.title,
                    status="error",
                    impacts=source.impacts,
                    sha256=None,
                    previous_sha256=previous_sha if isinstance(previous_sha, str) else None,
                    error=str(exc),
                )
            )
            continue

        if previous_sha is None:
            status = "baseline"
        elif previous_sha == snapshot.sha256:
            status = "unchanged"
        else:
            status = "changed"
            affected.update(source.impacts)
        stored[source.source_id] = {
            "category": source.category,
            "title": source.title,
            "url": source.url,
            "impacts": sorted(source.impacts),
            "sha256": snapshot.sha256,
            "size_bytes": snapshot.size_bytes,
            "content_type": snapshot.content_type,
            "encoding": snapshot.encoding,
            "final_url": snapshot.final_url,
            "checked_at": checked_at,
        }
        outcomes.append(
            SourceOutcome(
                source_id=source.source_id,
                category=source.category,
                title=source.title,
                status=status,
                impacts=source.impacts,
                sha256=snapshot.sha256,
                previous_sha256=previous_sha if isinstance(previous_sha, str) else None,
                error=None,
            )
        )

    report = RunReport(
        checked_at=checked_at,
        sources=tuple(outcomes),
        affected_products=frozenset(affected),
        has_errors=any(item.status == "error" for item in outcomes),
    )
    state["schema_version"] = 1
    state["checked_at"] = checked_at
    _atomic_json(state_path, state)
    _atomic_json(report_path, _report_payload(report))
    return report
