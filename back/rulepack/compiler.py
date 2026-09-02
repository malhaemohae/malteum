from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import jsonschema

from . import paths
from .embedding import E5SmallEmbedding, EmbeddingModel
from .pipeline import _load_find_span, canonical_json, count_exact_span
from .source_manifest import build_run_manifest


class CompileError(ValueError):
    pass


APPROVAL_KEY_ENV = "RULEPACK_APPROVAL_HMAC_KEY"


def approval_digest(bundle: dict[str, Any]) -> str:
    """사람이 본 RC 전체를 승인 파일에 결합하는 canonical SHA-256."""
    return hashlib.sha256(canonical_json(bundle).encode("utf-8")).hexdigest()


def approval_signature(approval: dict[str, Any], key: str) -> str:
    payload = {name: value for name, value in approval.items() if name != "approval_signature"}
    return hmac.new(
        key.encode("utf-8"), canonical_json(payload).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _approval_key() -> str:
    key = os.environ.get(APPROVAL_KEY_ENV, "")
    if len(key.encode("utf-8")) < 32:
        raise CompileError(f"{APPROVAL_KEY_ENV}에 32바이트 이상 승인 검증키가 필요함")
    return key


def _verify_approval_signature(approval: dict[str, Any], key: str) -> None:
    signature = approval.get("approval_signature", "")
    if not signature or not hmac.compare_digest(signature, approval_signature(approval, key)):
        raise CompileError("승인 서명 검증 실패")


def _load_source_audit(repo_root: Path) -> dict[str, Any]:
    return json.loads(
        (paths.config_dir(repo_root) / "source_audit.json").read_text(encoding="utf-8")
    )


def _verify_confirmed_freshness(
    code: str, evidence_doc_id: str, sources: dict[str, Any], audit: dict[str, Any]
) -> None:
    record = audit.get("candidates", {}).get(code)
    if not record or record.get("status") != "confirmed":
        raise CompileError(f"unverified_source 발행 차단: {code}")
    audit_doc_id = record.get("source_doc_id")
    if audit_doc_id != evidence_doc_id:
        raise CompileError(f"source_audit_candidate_mismatch 발행 차단: {code}")
    source = sources.get(audit_doc_id)
    if source is None or source.sha256 != record.get("source_sha256"):
        raise CompileError(f"source_audit_hash_mismatch 발행 차단: {code}")


def _korean_small_number(value: int) -> str:
    result = ""
    remaining = value
    for divisor, unit in ((1000, "천"), (100, "백"), (10, "십")):
        digit, remaining = divmod(remaining, divisor)
        if digit:
            result += ("" if digit == 1 else str(digit)) + unit
    return result + (str(remaining) if remaining else "")


def _numeric_tokens(value: str, unit: str) -> set[str]:
    """원문에 나올 수 있는 표기를 모은다.

    금액은 한국어 문서에서 여러 모양으로 적힌다. `100000000원` · `100,000,000원`
    · `1억원` · `1억 원`. 억 단위를 안 다루면 1억을 `10천만원` 으로 만들어 어느
    원문과도 안 맞는다. 예금자보호 한도가 5천만원이던 때는 안 드러났고, 2025-09-01
    시행 1억원 원천으로 갈아타면서 드러났다 (2026-08-30).
    """
    tokens = {f"{value}{unit}"}
    try:
        number = Decimal(value)
    except InvalidOperation:
        return tokens
    if number == number.to_integral_value():
        integer = int(number)
        tokens.add(f"{integer:,}{unit}")
        if unit == "원" and integer > 0 and integer % 10_000 == 0:
            # 억과 만을 함께 분해한다. 억의 배수만 따로 다루면 1억 5천만원이
            # 만 단위로 떨어져 `15천만원` 이 된다.
            eok, rest = divmod(integer, 100_000_000)
            man = rest // 10_000
            parts = []
            if eok:
                parts.append(f"{_korean_small_number(eok)}억")
            if man:
                parts.append(f"{_korean_small_number(man)}만")
            head = " ".join(parts)
            tokens.update({f"{head}원", f"{head} 원"})
    return tokens


def _validated_source_map(repo_root: Path, bundle: dict[str, Any]) -> dict[str, Any]:
    current = {source.doc_id: source for source in build_run_manifest(repo_root).sources}
    sources: dict[str, Any] = {}
    for source in bundle.get("sources", []):
        doc_id = source.get("doc_id")
        if not doc_id or doc_id in sources or doc_id not in current:
            raise CompileError(f"출처 doc_id 불일치 또는 중복: {doc_id}")
        if (
            source.get("sha256") != current[doc_id].sha256
            or source.get("page_count") != current[doc_id].page_count
        ):
            raise CompileError(f"출처 hash 또는 page_count 변경: {doc_id}")
        sources[doc_id] = current[doc_id]
    return sources


def _revalidate_evidence(
    repo_root: Path, code: str, evidence: dict[str, Any], sources: dict[str, Any], prefix: str
) -> dict[str, Any]:
    doc_id = evidence.get("doc_id")
    if doc_id not in sources:
        raise CompileError(f"{prefix} 출처 없는 doc_id: {code}")
    source = sources[doc_id]
    hit = _load_find_span(repo_root)(str(source.path), evidence["span"], evidence["page"])
    if hit is None or count_exact_span(source.path, evidence["span"], evidence["page"]) != 1:
        raise CompileError(f"{prefix} span 재검증 실패 또는 모호함: {code}")
    bbox = evidence.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4 or hit["bbox"] != bbox:
        raise CompileError(f"{prefix} bbox 재검증 실패: {code}")
    return hit


def _revalidate_candidate(repo_root: Path, item: dict[str, Any], sources: dict[str, Any]) -> None:
    _revalidate_evidence(repo_root, item["code"], item["evidence"], sources, "항목")
    for fact in item.get("numeric_facts", []):
        value = fact.get("value", "")
        if not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
            raise CompileError(f"numeric_fact value 형식 오류: {item['code']}")
        evidence = fact.get("evidence")
        if not evidence:
            raise CompileError(f"numeric_fact evidence 없음: {item['code']}")
        _revalidate_evidence(repo_root, item["code"], evidence, sources, "numeric_fact")
        span = evidence["span"]
        tokens = _numeric_tokens(value, fact.get("unit", ""))
        if fact.get("label", "") not in span or not any(token in span for token in tokens):
            raise CompileError(f"numeric_fact 라벨·값 연결 오류: {item['code']}")
        condition = fact.get("condition")
        if condition and condition not in span:
            raise CompileError(f"numeric_fact 조건 연결 오류: {item['code']}")


def _schema_item(
    item: dict[str, Any], approval: dict[str, Any], model: EmbeddingModel
) -> dict[str, Any]:
    result = {
        key: item[key]
        for key in (
            "code",
            "name",
            "type",
            "requirement_elements",
            "legal_basis",
            "evidence",
            "plain_language",
        )
    }
    if item.get("axis"):
        result["axis"] = item["axis"]
    for key in ("numeric_facts", "documents_required", "forbidden_examples", "risk_examples"):
        if key in item:
            result[key] = item[key]
    # L1 정규식 판정의 기준. 설정(candidate_rules)에서 오고, 없으면 그 항목은
    # L1 을 건너뛰어 L2·L3 로 간다.
    result["l1_patterns"] = item.get("l1_patterns", [])
    # 접두어는 벡터를 만든 구현이 정한다. 모델이 바뀌면 벡터도 바뀌므로
    # 식별자가 같으면 어느 모델 것인지 구분되지 않는다.
    result["embedding_id"] = f"{model.id_prefix}:{item['code']}"
    result["approved_at"] = approval["approved_at"]
    result["approved_by"] = approval["approved_by"]
    return result


def _validate_pack_schema(repo_root: Path, pack: dict[str, Any]) -> None:
    schema = json.loads(
        (paths.contracts_dir(repo_root) / "rulepack.schema.json").read_text(encoding="utf-8")
    )
    errors = list(
        jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        ).iter_errors(pack)
    )
    if errors:
        raise CompileError("schema 검증 실패: " + "; ".join(error.message for error in errors))


def _compile_pack(
    repo_root: Path,
    bundle: dict[str, Any],
    approval: dict[str, Any],
    version: str,
    *,
    allow_unverified: bool,
    model: EmbeddingModel,
) -> dict[str, Any]:
    required = {"approved_by", "approved_at", "item_codes", "bundle_sha256"}
    if (
        not required <= approval.keys()
        or not approval.get("approved_by")
        or not approval.get("item_codes")
    ):
        raise CompileError("명시적 승인자, 승인시각, 승인 항목, 묶음 digest가 필요함")
    approval_key = ""
    if not allow_unverified:
        approval_key = _approval_key()
        _verify_approval_signature(approval, approval_key)
    if approval["bundle_sha256"] != approval_digest(bundle):
        raise CompileError("승인 후 검토 묶음이 변경됨")
    codes = approval["item_codes"]
    if len(codes) != len(set(codes)):
        raise CompileError("승인 항목 code 중복")
    sources = _validated_source_map(repo_root, bundle)
    audit = _load_source_audit(repo_root)
    by_code = {item["code"]: item for item in bundle["items"]}
    if len(by_code) != len(bundle["items"]):
        raise CompileError("검토 묶음 item code 중복")

    selected = []
    for code in codes:
        if code not in by_code:
            raise CompileError(f"승인 목록에 없는 후보: {code}")
        item = by_code[code]
        if not allow_unverified and item.get("publication_blocker"):
            raise CompileError(f"{item['publication_blocker']} 발행 차단: {code}")
        if item["status"] != "evidence_verified":
            raise CompileError(f"근거 검증 미통과 후보: {code}")
        _revalidate_candidate(repo_root, item, sources)
        if not allow_unverified:
            _verify_confirmed_freshness(code, item["evidence"]["doc_id"], sources, audit)
        selected.append(_schema_item(item, approval, model))

    pack = {
        "schema_version": "1",
        "pack_version": version,
        "product": bundle["product"],
        "published_at": approval["approved_at"],
        "published_by": approval["approved_by"],
        "embedding": {"model": model.name, "dim": model.dim, "normalized": model.normalized},
        # ⑧ 용어 밀도 게이지가 세는 목록. 상품마다 다르므로 설정에서 가져온다.
        # 실시간 판단 없이 이 목록 대조로만 세므로 게이지가 결정적이다.
        "jargon_terms": bundle.get("jargon_terms", []),
        "sources": [
            {
                key: source[key]
                for key in ("doc_id", "title", "publisher", "url", "snapshot_date", "page_count")
            }
            for source in bundle["sources"]
        ],
        "items": selected,
    }
    _validate_pack_schema(repo_root, pack)
    return pack


def compile_pack(
    repo_root: Path,
    bundle: dict[str, Any],
    approval: dict[str, Any],
    version: str,
    model: EmbeddingModel | None = None,
) -> dict[str, Any]:
    """운영 컴파일. 최신성이 confirmed인 승인 항목만 허용함."""
    model = model or E5SmallEmbedding()
    pack = _compile_pack(repo_root, bundle, approval, version, allow_unverified=False, model=model)
    attestation_payload = {
        "artifact_kind": "production_compiled",
        "approval_signature": approval["approval_signature"],
        "pack_sha256": hashlib.sha256(canonical_json(pack).encode("utf-8")).hexdigest(),
    }
    return {
        **attestation_payload,
        "production_publishable": True,
        "compiler_attestation": hmac.new(
            _approval_key().encode("utf-8"),
            canonical_json(attestation_payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest(),
        "pack": pack,
    }


def compile_synthetic_pack(
    repo_root: Path,
    bundle: dict[str, Any],
    approval: dict[str, Any],
    version: str,
    model: EmbeddingModel | None = None,
) -> dict[str, Any]:
    """스키마 경로 검증 전용. 반환 envelope는 운영 publish 입력이 될 수 없음."""
    model = model or E5SmallEmbedding()
    pack = _compile_pack(repo_root, bundle, approval, version, allow_unverified=True, model=model)
    return {"artifact_kind": "synthetic_dry_run", "production_publishable": False, "pack": pack}


def verified_pack(compiled: dict[str, Any]) -> dict[str, Any]:
    """운영 컴파일 envelope 에서 팩을 꺼낸다. 서명과 내용 해시를 둘 다 대조한다.

    발행과 적재가 같은 검사를 거치게 하려고 함수로 뺐다. 적재 쪽이 이 검사를
    건너뛰면 발행 시점부터 DB 에 들어가기 전까지의 구간(아티팩트 저장소·공유
    폴더·수동 복사)에서 팩을 고쳐도 아무도 모른다. 팩은 창구 판정의 기준이라
    금액 한 자리만 바뀌어도 시스템이 틀린 것을 가르치게 된다 (2026-08-30).
    """
    if compiled.get("artifact_kind") != "production_compiled" or not compiled.get(
        "production_publishable"
    ):
        raise CompileError("운영 컴파일 attestation이 없는 산출물은 쓸 수 없음")
    attestation_payload = {
        "artifact_kind": compiled["artifact_kind"],
        "approval_signature": compiled.get("approval_signature"),
        "pack_sha256": compiled.get("pack_sha256"),
    }
    expected = hmac.new(
        _approval_key().encode("utf-8"),
        canonical_json(attestation_payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(compiled.get("compiler_attestation", ""), expected):
        raise CompileError("운영 컴파일 attestation 검증 실패")
    pack = compiled.get("pack")
    if not isinstance(pack, dict) or hashlib.sha256(
        canonical_json(pack).encode("utf-8")
    ).hexdigest() != compiled.get("pack_sha256"):
        raise CompileError("컴파일 뒤 pack 내용이 변경됨")
    return pack


def publish_immutable(compiled: dict[str, Any], output_dir: Path) -> str:
    pack = verified_pack(compiled)
    version = pack.get("pack_version", "")
    if not re.fullmatch(r"[A-Z]{3,4}-\d{4}\.\d{2}-v\d+", version):
        raise CompileError("pack_version 명명 규칙 위반")
    _validate_pack_schema(paths.find_repo_root(), pack)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"rulepack_{version}.json"
    content = canonical_json(pack) + "\n"
    for prior_path in output_dir.glob("rulepack_*.json"):
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        if prior.get("product", {}).get("code") != pack["product"]["code"]:
            continue
        prior_by_code = {item["code"]: item["name"] for item in prior["items"]}
        prior_by_name = {item["name"]: item["code"] for item in prior["items"]}
        for item in pack["items"]:
            if item["name"] in prior_by_name and prior_by_name[item["name"]] != item["code"]:
                raise CompileError(f"동일 의미 항목 code 변경 금지: {item['name']}")
            if item["code"] in prior_by_code and prior_by_code[item["code"]] != item["name"]:
                raise CompileError(f"기존 code의 의미 변경 금지: {item['code']}")
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        return "created"
    except FileExistsError:
        if path.read_text(encoding="utf-8") == content:
            return "no_op"
        raise CompileError("같은 pack_version에 다른 내용이 존재함") from None
