from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from . import paths
from .adapters import CandidateExtractor, DeterministicRuleAdapter, extract_batch
from .source_manifest import build_run_manifest
from .structure import StructureChunk, build_chunks_from_structure, extract_documents

CANDIDATE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "code",
        "name",
        "candidate_kind",
        "requirement_elements",
        "legal_basis",
        "evidence",
        "plain_language",
        "source_chunk_id",
        "prompt_version",
        "model",
    ],
    "properties": {
        "code": {"type": "string"},
        "name": {"type": "string"},
        "candidate_kind": {"type": "string"},
        "type": {"type": ["string", "null"]},
        "axis": {"type": ["string", "null"]},
        "requirement_elements": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "legal_basis": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["law", "article"],
                "properties": {"law": {"type": "string"}, "article": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        "evidence": {
            "type": "object",
            "required": ["doc_id", "page", "span"],
            "properties": {
                "doc_id": {"type": "string"},
                "page": {"type": "integer", "minimum": 1},
                "span": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        },
        "plain_language": {"type": "array", "items": {"type": "string"}},
        "source_chunk_id": {"type": "string"},
        "prompt_version": {"type": "string"},
        "model": {"type": "string"},
        "numeric_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "value", "unit"],
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                    "condition": {"type": "string"},
                    "tolerance": {"type": "number"},
                },
                "additionalProperties": False,
            },
        },
        "documents_required": {"type": "array", "items": {"type": "string"}},
        "forbidden_examples": {"type": "array", "items": {"type": "string"}},
        "risk_examples": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_find_span(repo_root: Path):
    path = paths.contracts_dir(repo_root) / "find_span.py"
    spec = importlib.util.spec_from_file_location("malteum_contract_find_span", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("contracts/find_span.py 로드 실패")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.find_span


def _candidate_from_rule(rule: dict[str, Any], chunk_id: str, model: str) -> dict[str, Any]:
    candidate = {
        "code": rule["code"],
        "name": rule["name"],
        "candidate_kind": rule.get("candidate_kind", "rulepack_item"),
        "type": rule.get("type"),
        "axis": rule.get("axis"),
        "requirement_elements": rule["requirements"],
        "legal_basis": [{"law": rule["law"], "article": rule["article"]}],
        "evidence": {"doc_id": rule["doc_id"], "page": rule["page"], "span": rule["span"]},
        "plain_language": rule["plain"],
        "source_chunk_id": chunk_id,
        "prompt_version": "candidate-v1",
        "model": model,
    }
    for key in ("numeric_facts", "documents_required", "forbidden_examples", "risk_examples"):
        if key in rule:
            candidate[key] = rule[key]
    return candidate


def _chunk_id(chunk: StructureChunk) -> str:
    raw = f"{chunk.doc_id}:{chunk.page}:{'/'.join(chunk.structure_path)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _rank_chunk(chunk: StructureChunk, rule: dict[str, Any]) -> tuple[int, int]:
    same_page = chunk.page == rule["page"]
    contains_span = rule["span"] in chunk.text
    return (
        0 if same_page and contains_span else 1 if same_page else 2 if contains_span else 3,
        chunk.page,
    )


def _chunk_supports_evidence(chunk: StructureChunk, evidence: dict[str, Any]) -> bool:
    if chunk.doc_id != evidence["doc_id"] or chunk.page != evidence["page"]:
        return False
    if evidence["span"] in chunk.text:
        return True
    if chunk.kind != "table":
        return False

    def without_layout(value: str) -> str:
        return "".join(value.replace("|", "").split())

    return without_layout(evidence["span"]) in without_layout(chunk.text)


def _candidate_prompt(candidate: dict[str, Any], matches: list[StructureChunk]) -> str:
    return canonical_json(
        {
            "task": "아래 source_chunks에서 candidate 스키마에 맞는 후보 한 건을 추출함",
            "candidate": candidate,
            "source_chunks": [
                {
                    "doc_id": chunk.doc_id,
                    "page": chunk.page,
                    "structure_path": list(chunk.structure_path),
                    "text": chunk.text,
                }
                for chunk in matches
            ],
        }
    )


def count_exact_span(pdf_path: Path, span: str, page: int) -> int:
    """좌표는 만들지 않고 지정 페이지의 exact span 개수만 세어 모호성을 판정함."""
    document = pdfium.PdfDocument(pdf_path)
    try:
        text_page = document[page - 1].get_textpage()
        searcher = text_page.search(span, match_case=True, match_whole_word=False)
        count = 0
        while searcher.get_next() is not None:
            count += 1
        return count
    finally:
        document.close()


def build_product_bundle(
    repo_root: Path,
    product: str,
    rules_path: Path,
    work_dir: Path,
    extractor: CandidateExtractor | None = None,
) -> dict[str, Any]:
    run = build_run_manifest(repo_root)
    products = json.loads(
        (paths.config_dir(repo_root) / "products.json").read_text(encoding="utf-8")
    )
    rules_doc = json.loads(rules_path.read_text(encoding="utf-8"))
    product_config = products[product]
    selected = [source for source in run.sources if source.doc_id in product_config["document_ids"]]
    documents = extract_documents(selected, work_dir / "structure")
    chunks = [chunk for document in documents for chunk in build_chunks_from_structure(document)]
    find_span = _load_find_span(repo_root)
    source_by_id = {source.doc_id: source for source in selected}
    adapter = extractor or DeterministicRuleAdapter()
    audit = json.loads(
        (paths.config_dir(repo_root) / "source_audit.json").read_text(encoding="utf-8")
    )

    prepared: dict[str, tuple[dict[str, Any], list[StructureChunk]]] = {}
    requests: list[tuple[str, str, dict[str, Any]]] = []
    for rule in rules_doc["products"][product]:
        matches = sorted(
            [
                chunk
                for chunk in chunks
                if chunk.doc_id == rule["doc_id"]
                and (rule["trigger"] in chunk.text or rule["span"] in chunk.text)
            ],
            key=lambda chunk: _rank_chunk(chunk, rule),
        )
        chunk_id = _chunk_id(matches[0]) if matches else ""
        seed = _candidate_from_rule(rule, chunk_id, adapter.model)
        prepared[rule["code"]] = (rule, matches)
        requests.append((rule["code"], _candidate_prompt(seed, matches), CANDIDATE_OUTPUT_SCHEMA))
    extracted, extraction_failures = extract_batch(adapter, requests)

    items: list[dict[str, Any]] = []
    for code, (rule, matches) in prepared.items():
        candidate = extracted.get(code) or _candidate_from_rule(rule, "", adapter.model)
        candidate["raw_structured_response"] = canonical_json(
            extracted.get(code, {"error": extraction_failures.get(code)})
        )
        freshness = audit.get("candidates", {}).get(code, audit["default"])
        candidate["freshness"] = freshness["status"]
        candidate["freshness_reason"] = freshness["reason"]
        if freshness.get("publication_blocker"):
            audited_source = source_by_id.get(freshness.get("source_doc_id"))
            if audited_source and audited_source.sha256 == freshness.get("source_sha256"):
                candidate["publication_blocker"] = freshness["publication_blocker"]
            else:
                candidate["publication_blocker"] = "source_audit_hash_mismatch"
        if code in extraction_failures:
            candidate.update(
                status="review_required",
                reason_code="llm_extraction_failed",
                reason=extraction_failures[code],
            )
            items.append(candidate)
            continue
        if not matches:
            candidate.update(
                status="review_required",
                reason_code="candidate_trigger_missing",
                reason="구조 chunk에서 trigger를 찾지 못함",
            )
            items.append(candidate)
            continue

        evidence = candidate["evidence"]
        source = source_by_id.get(evidence["doc_id"])
        if source is None:
            candidate.update(
                status="rejected",
                reason_code="evidence_source_unmapped",
                reason="상품 원천 목록에 없는 doc_id임",
            )
            items.append(candidate)
            continue
        if evidence["page"] > source.page_count:
            candidate.update(
                status="rejected",
                reason_code="evidence_not_found_or_page_mismatch",
                reason="지정 page가 원천 범위를 벗어남",
            )
            items.append(candidate)
            continue
        hit = find_span(str(source.path), evidence["span"], evidence["page"])
        if hit is None:
            candidate.update(
                status="rejected",
                reason_code="evidence_not_found_or_page_mismatch",
                reason="지정 페이지에서 exact span을 찾지 못함",
            )
            items.append(candidate)
            continue
        if count_exact_span(source.path, evidence["span"], evidence["page"]) != 1:
            candidate.update(
                status="review_required",
                reason_code="evidence_ambiguous",
                reason="지정 페이지에서 exact span이 여러 번 발견됨",
            )
            items.append(candidate)
            continue
        candidate["evidence"]["bbox"] = hit["bbox"]
        matching_chunks = {_chunk_id(chunk): chunk for chunk in matches}
        source_chunk = matching_chunks.get(candidate["source_chunk_id"])
        if source_chunk is None or not _chunk_supports_evidence(source_chunk, evidence):
            candidate["preview_ref"] = f"{evidence['doc_id']}.pdf#page={evidence['page']}"
            candidate.update(
                status="review_required",
                reason_code="candidate_chunk_mismatch",
                reason="후보 evidence가 모델에 전달된 source chunk와 연결되지 않음",
            )
            items.append(candidate)
            continue
        for fact in candidate.get("numeric_facts", []):
            fact["evidence"] = dict(candidate["evidence"])

        if rule.get("manual_review_reason"):
            candidate.update(
                status="review_required",
                reason_code=rule["manual_review_reason"],
                reason="exact span은 있으나 요구 요건 전체의 의미 근거가 부족함",
            )
        else:
            candidate.update(status="evidence_verified", reason_code=None, reason=None)
        candidate["preview_ref"] = f"{evidence['doc_id']}.pdf#page={evidence['page']}"
        items.append(candidate)

    counts = {
        state: sum(item["status"] == state for item in items)
        for state in ("evidence_verified", "rejected", "review_required")
    }
    return {
        "artifact_kind": "release_candidate",
        "product": {
            "code": product_config["code"],
            "name": product_config["name"],
            "category": product,
        },
        "parser": {"name": run.parser.name, "version": run.parser.version},
        "sources": [
            {
                "doc_id": source.doc_id,
                "title": source.title,
                "publisher": source.publisher,
                "url": source.url,
                "snapshot_date": source.snapshot_date,
                "page_count": source.page_count,
                "sha256": source.sha256,
            }
            for source in selected
        ],
        "items": items,
        "counts": counts,
        "approval_status": "human_approval_required",
    }
