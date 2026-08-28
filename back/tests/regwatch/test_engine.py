from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from regwatch.engine import run_monitor
from regwatch.fetcher import FetchError
from regwatch.models import FetchResponse, SourceSpec


class _SequenceFetcher:
    def __init__(self, responses: dict[str, list[FetchResponse | Exception]]) -> None:
        self._responses = responses

    def fetch(self, source: SourceSpec) -> FetchResponse:
        value = self._responses[source.source_id].pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _source(source_id: str, impact: str) -> SourceSpec:
    return SourceSpec(
        source_id=source_id,
        category=1,
        title=source_id,
        url=f"https://example.com/{source_id}",
        mode="html",
        impacts=frozenset({impact}),
        allowed_hosts=frozenset({"example.com"}),
        max_bytes=1_024,
    )


def _response(text: str, source_id: str) -> FetchResponse:
    return FetchResponse(
        body=f"<main>{text}</main>".encode(),
        content_type="text/html",
        final_url=f"https://example.com/{source_id}",
    )


def test_first_run_is_baseline_and_identical_second_run_is_unchanged(tmp_path: Path) -> None:
    source = _source("law", "deposit")
    fetcher = _SequenceFetcher({"law": [_response("same", "law"), _response("same", "law")]})
    state = tmp_path / "state.json"
    report = tmp_path / "report.json"

    first = run_monitor(
        (source,), fetcher, state, report, now=lambda: datetime(2026, 8, 26, tzinfo=UTC)
    )
    second = run_monitor(
        (source,), fetcher, state, report, now=lambda: datetime(2026, 8, 27, tzinfo=UTC)
    )

    assert [item.status for item in first.sources] == ["baseline"]
    assert first.affected_products == frozenset()
    assert [item.status for item in second.sources] == ["unchanged"]
    assert json.loads(report.read_text(encoding="utf-8"))["summary"]["unchanged"] == 1


def test_changed_source_reports_only_its_impacted_product(tmp_path: Path) -> None:
    source = _source("terms", "loan")
    state = tmp_path / "state.json"
    report = tmp_path / "report.json"
    baseline = _SequenceFetcher({"terms": [_response("old", "terms")]})
    changed = _SequenceFetcher({"terms": [_response("new", "terms")]})

    run_monitor((source,), baseline, state, report)
    result = run_monitor((source,), changed, state, report)

    assert result.sources[0].status == "changed"
    assert result.sources[0].previous_sha256 != result.sources[0].sha256
    assert result.affected_products == frozenset({"loan"})


def test_failure_preserves_last_good_state_and_does_not_stop_other_sources(tmp_path: Path) -> None:
    deposit = _source("deposit-law", "deposit")
    loan = replace(_source("loan-law", "loan"), category=2)
    state = tmp_path / "state.json"
    report = tmp_path / "report.json"
    run_monitor(
        (deposit, loan),
        _SequenceFetcher(
            {
                "deposit-law": [_response("old deposit", "deposit-law")],
                "loan-law": [_response("old loan", "loan-law")],
            }
        ),
        state,
        report,
    )
    before = json.loads(state.read_text(encoding="utf-8"))["sources"]["deposit-law"]["sha256"]

    result = run_monitor(
        (deposit, loan),
        _SequenceFetcher(
            {
                "deposit-law": [FetchError("temporary outage")],
                "loan-law": [_response("new loan", "loan-law")],
            }
        ),
        state,
        report,
    )
    after = json.loads(state.read_text(encoding="utf-8"))["sources"]["deposit-law"]["sha256"]

    assert [(item.source_id, item.status) for item in result.sources] == [
        ("deposit-law", "error"),
        ("loan-law", "changed"),
    ]
    assert result.has_errors is True
    assert result.affected_products == frozenset({"loan"})
    assert after == before
