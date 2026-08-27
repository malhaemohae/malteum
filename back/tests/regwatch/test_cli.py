from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from regwatch.cli import main
from regwatch.fetcher import FetchError
from regwatch.models import FetchResponse, SourceSpec


class _AllGoodFetcher:
    def fetch(self, source: SourceSpec) -> FetchResponse:
        body = (
            b"%PDF-1.7\nfixture"
            if source.mode == "pdf"
            else f"<main>{source.source_id}</main>".encode()
        )
        content_type = "application/pdf" if source.mode == "pdf" else "text/html"
        return FetchResponse(body=body, content_type=content_type, final_url=source.url)


class _OneFailureFetcher(_AllGoodFetcher):
    def fetch(self, source: SourceSpec) -> FetchResponse:
        if source.source_id == "law-fcp-act":
            raise FetchError("network down")
        return super().fetch(source)


def _paths(tmp_path: Path) -> list[str]:
    config = Path(__file__).resolve().parents[2] / "regwatch" / "config" / "sources.json"
    return [
        "run",
        "--config",
        str(config),
        "--state",
        str(tmp_path / "state.json"),
        "--report",
        str(tmp_path / "report.json"),
    ]


def test_cli_creates_baseline_and_returns_zero(tmp_path: Path, capsys) -> None:
    exit_code = main(_paths(tmp_path), fetcher=_AllGoodFetcher())

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["summary"]["baseline"] == 18
    assert output["has_errors"] is False
    assert (tmp_path / "state.json").is_file()


def test_cli_returns_two_when_any_source_fails(tmp_path: Path, capsys) -> None:
    exit_code = main(_paths(tmp_path), fetcher=_OneFailureFetcher())

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert output["summary"]["error"] == 1
    assert output["has_errors"] is True


def test_cli_returns_two_and_json_when_config_cannot_be_read(tmp_path: Path, capsys) -> None:

    args = _paths(tmp_path)
    args[2] = str(tmp_path / "missing-sources.json")

    exit_code = main(args, fetcher=_AllGoodFetcher())

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert output["has_errors"] is True
    assert "원천 설정" in output["error"]


def test_cli_module_returns_two_and_json_when_state_is_corrupt(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{not-json", encoding="utf-8")
    report_path = tmp_path / "report.json"
    config = Path(__file__).resolve().parents[2] / "regwatch" / "config" / "sources.json"
    package_root = Path(__file__).resolve().parents[2]  # back (flat 배치의 패키지 루트)
    environment = os.environ | {"PYTHONPATH": str(package_root), "PYTHONIOENCODING": "utf-8"}

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "regwatch.cli",
            "run",
            "--config",
            str(config),
            "--state",
            str(state_path),
            "--report",
            str(report_path),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=environment,
    )

    output = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert output["has_errors"] is True
