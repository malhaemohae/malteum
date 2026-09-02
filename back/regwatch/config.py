from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from .models import SourceSpec


class ConfigError(ValueError):
    """원천 설정이 안전 계약을 위반함."""


_CATEGORIES = set(range(1, 8))
_IMPACTS = {"deposit", "loan"}
_MODES = {"html", "fss_board", "pdf"}


def _required_text(row: dict[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} 값이 비어 있음")
    return value.strip()


def load_sources(path: Path) -> tuple[SourceSpec, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"원천 설정을 읽지 못함: {exc}") from exc

    rows = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ConfigError("sources 배열이 필요함")

    seen_ids: set[str] = set()
    specs: list[SourceSpec] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ConfigError("각 source는 객체여야 함")
        source_id = _required_text(raw, "id")
        if source_id in seen_ids:
            raise ConfigError(f"중복 source id: {source_id}")
        seen_ids.add(source_id)

        category = raw.get("category")
        if (
            not isinstance(category, int)
            or isinstance(category, bool)
            or category not in _CATEGORIES
        ):
            raise ConfigError(f"category는 1~7 정수여야 함: {source_id}")

        url = _required_text(raw, "url")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ConfigError(f"HTTPS URL만 허용함: {source_id}")

        hosts = raw.get("allowed_hosts")
        if (
            not isinstance(hosts, list)
            or not hosts
            or not all(isinstance(host, str) and host for host in hosts)
        ):
            raise ConfigError(f"허용 호스트 목록이 필요함: {source_id}")
        allowed_hosts = frozenset(host.lower() for host in hosts)
        if parsed.hostname.lower() not in allowed_hosts:
            raise ConfigError(f"URL이 허용 호스트에 속하지 않음: {source_id}")

        impacts = raw.get("impacts")
        if not isinstance(impacts, list) or not impacts or not set(impacts) <= _IMPACTS:
            raise ConfigError(f"영향 상품은 deposit 또는 loan이어야 함: {source_id}")

        mode = _required_text(raw, "mode")
        if mode not in _MODES:
            raise ConfigError(f"mode는 html 또는 pdf여야 함: {source_id}")

        max_bytes = raw.get("max_bytes", 8_000_000)
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or not 1_024 <= max_bytes <= 50_000_000
        ):
            raise ConfigError(f"max_bytes 범위가 잘못됨: {source_id}")

        specs.append(
            SourceSpec(
                source_id=source_id,
                category=category,
                title=_required_text(raw, "title"),
                url=url,
                mode=mode,
                impacts=frozenset(impacts),
                allowed_hosts=allowed_hosts,
                max_bytes=max_bytes,
            )
        )

    categories = {source.category for source in specs}
    if categories != _CATEGORIES:
        raise ConfigError(f"범주 1~7이 모두 필요함: 실제 {sorted(categories)}")
    return tuple(sorted(specs, key=lambda source: (source.category, source.source_id)))
