from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    category: int
    title: str
    url: str
    mode: str
    impacts: frozenset[str]
    allowed_hosts: frozenset[str]
    max_bytes: int


@dataclass(frozen=True)
class FetchResponse:
    body: bytes
    content_type: str
    final_url: str
    encoding: str | None = None


@dataclass(frozen=True)
class ResourceSnapshot:
    source_id: str
    sha256: str
    size_bytes: int
    final_url: str
    content_type: str
    encoding: str | None


@dataclass(frozen=True)
class SourceOutcome:
    source_id: str
    category: int
    title: str
    status: str
    impacts: frozenset[str]
    sha256: str | None
    previous_sha256: str | None
    error: str | None


@dataclass(frozen=True)
class RunReport:
    checked_at: str
    sources: tuple[SourceOutcome, ...]
    affected_products: frozenset[str]
    has_errors: bool
