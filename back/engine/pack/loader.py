"""팩 JSON → RulePack. 임베딩 차원 검사. L1 패턴 컴파일은 compiler.py 가 생기면 그쪽으로."""

from __future__ import annotations

from typing import Any

from contracts.engine_contract import Evidence, NumericFact, PackItem
from engine.pack.source import PackSource
from engine.types import RulePack


class PackRejected(ValueError):
    pass


def load_pack(source: PackSource, pack_version: str, embedder_dim: int | None = None) -> RulePack:
    raw = source.read(pack_version)
    if raw.get("pack_version") != pack_version:
        raise PackRejected(f"요청 {pack_version} 인데 팩은 {raw.get('pack_version')}")
    dim = raw["embedding"]["dim"]
    if embedder_dim is not None and dim != embedder_dim:
        raise PackRejected(f"팩 임베딩 차원 {dim} ≠ 임베더 {embedder_dim}")
    return RulePack(
        pack_version=pack_version,
        product_code=raw["product"]["code"],
        product_name=raw["product"]["name"],
        embedding_model=raw["embedding"]["model"],
        embedding_dim=dim,
        items=tuple(_item(it) for it in raw["items"]),
    )


def _evidence(e: dict[str, Any]) -> Evidence:
    bbox = e.get("bbox")
    return Evidence(
        doc_id=e["doc_id"],
        page=e["page"],
        span=e["span"],
        bbox=tuple(bbox) if bbox else None,
        legal_basis=e.get("legal_basis"),
    )


def _item(it: dict[str, Any]) -> PackItem:
    return PackItem(
        code=it["code"],
        name=it["name"],
        type=it["type"],
        requirement_elements=tuple(it["requirement_elements"]),
        evidence=_evidence(it["evidence"]),
        axis=it.get("axis"),
        l1_patterns=tuple((p["kind"], p["value"]) for p in it.get("l1_patterns", [])),
        plain_language=tuple(it.get("plain_language", [])),
        numeric_facts=tuple(
            NumericFact(
                label=n["label"],
                value=n["value"],
                unit=n["unit"],
                condition=n.get("condition"),
                tolerance=n.get("tolerance", 0.0),
            )
            for n in it.get("numeric_facts", [])
        ),
        documents_required=tuple(it.get("documents_required", [])),
        forbidden_examples=tuple(it.get("forbidden_examples", [])),
        risk_examples=tuple(it.get("risk_examples", [])),
    )
