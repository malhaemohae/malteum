from __future__ import annotations

import json
from pathlib import Path

import pytest

from regwatch.config import ConfigError, load_sources


def _write(path: Path, sources: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return path


def _source(category: int, source_id: str | None = None) -> dict[str, object]:
    return {
        "id": source_id or f"source-{category}",
        "category": category,
        "title": f"source {category}",
        "url": f"https://example.com/source/{category}",
        "mode": "html",
        "impacts": ["deposit", "loan"],
        "allowed_hosts": ["example.com"],
    }


def test_load_sources_requires_every_category_from_one_through_seven(tmp_path: Path) -> None:
    config = _write(tmp_path / "sources.json", [_source(category) for category in range(1, 7)])

    with pytest.raises(ConfigError, match="범주 1~7"):
        load_sources(config)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda rows: rows.append(_source(7, "source-1")), "중복 source id"),
        (lambda rows: rows[0].update(url="http://example.com/unsafe"), "HTTPS"),
        (lambda rows: rows[0].update(impacts=["insurance"]), "영향 상품"),
        (lambda rows: rows[0].update(allowed_hosts=["other.example"]), "허용 호스트"),
    ],
)
def test_load_sources_rejects_unsafe_or_ambiguous_contracts(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    rows = [_source(category) for category in range(1, 8)]
    mutate(rows)
    config = _write(tmp_path / "sources.json", rows)

    with pytest.raises(ConfigError, match=message):
        load_sources(config)


def test_load_sources_returns_immutable_ordered_specs(tmp_path: Path) -> None:
    rows = [_source(category) for category in reversed(range(1, 8))]
    config = _write(tmp_path / "sources.json", rows)

    sources = load_sources(config)

    assert isinstance(sources, tuple)
    assert [source.category for source in sources] == list(range(1, 8))
    assert sources[0].impacts == frozenset({"deposit", "loan"})
