from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from rulepack.adapters import AdapterError, OpenAICompatibleAdapter
from rulepack.cli import _java_major, _require_java17, main
from rulepack.compiler import (
    CompileError,
    approval_digest,
    approval_signature,
    compile_pack,
    compile_synthetic_pack,
    publish_immutable,
)
from rulepack.pipeline import build_product_bundle, canonical_json, count_exact_span
from rulepack.source_manifest import build_run_manifest

REPO_ROOT = Path(__file__).resolve().parents[3]

from rulepack import paths  # noqa: E402

RULES = paths.config_dir(REPO_ROOT) / "candidate_rules.json"
TEST_APPROVAL_KEY = "test-approval-key-that-is-at-least-32-bytes"


@pytest.fixture(scope="module")
def bundles(tmp_path_factory: pytest.TempPathFactory):
    work = tmp_path_factory.mktemp("pipeline")
    return {
        product: build_product_bundle(REPO_ROOT, product, RULES, work / product)
        for product in ("deposit", "loan")
    }


def _approval(
    bundle: dict, code: str, approved_by: str = "test-reviewer", *, signed: bool = False
) -> dict:
    approval = {
        "approved_by": approved_by,
        "approved_at": "2026-08-26T00:00:00Z",
        "item_codes": [code],
        "bundle_sha256": approval_digest(bundle),
    }
    if signed:
        approval["approval_signature"] = approval_signature(approval, TEST_APPROVAL_KEY)
    return approval


def _confirmed_audit(bundle: dict, code: str) -> dict:
    item = next(item for item in bundle["items"] if item["code"] == code)
    doc_id = item["evidence"]["doc_id"]
    source = next(source for source in bundle["sources"] if source["doc_id"] == doc_id)
    return {
        "default": {"status": "unverified"},
        "candidates": {
            code: {
                "status": "confirmed",
                "source_doc_id": doc_id,
                "source_sha256": source["sha256"],
            }
        },
    }


def _without_publication_blocker(bundle: dict, code: str) -> dict:
    changed = deepcopy(bundle)
    item = next(item for item in changed["items"] if item["code"] == code)
    item.pop("publication_blocker", None)
    return changed


def test_two_product_build_is_deterministic_and_isolates_rejections(bundles) -> None:
    deposit = bundles["deposit"]
    loan = bundles["loan"]
    assert canonical_json(deposit) == canonical_json(json.loads(canonical_json(deposit)))
    assert canonical_json(loan) == canonical_json(json.loads(canonical_json(loan)))
    assert any(item["status"] == "rejected" for item in deposit["items"])
    assert any(item["status"] == "rejected" for item in loan["items"])
    assert any(item["status"] == "evidence_verified" for item in deposit["items"])
    assert any(item["status"] == "evidence_verified" for item in loan["items"])
    assert all(
        item.get("evidence", {}).get("bbox")
        for bundle in bundles.values()
        for item in bundle["items"]
        if item["status"] == "evidence_verified"
    )


def test_risk_signal_uses_risk_type_and_never_forbidden(bundles) -> None:
    """위험 신호는 `risk` 로 나가야 하고 `forbidden` 으로 우회하면 안 된다.

    위험 신호는 고객 발화 대상이라 경보만 만든다. `forbidden` 으로 밀어넣으면
    고객이 한 말이 은행원의 위반으로 표시되어 P6 위반이 된다.

    계약에 `risk` 가 없던 8/26 에는 검토 대기로 묶는 것이 그 보호였다. v0.4
    (`79ce386`, 8/27)가 type 을 추가해 이제 정상 발행된다 (2026-08-29).
    """
    risks = [
        item
        for bundle in bundles.values()
        for item in bundle["items"]
        if item.get("candidate_kind") == "risk_signal"
    ]
    assert risks
    assert {item["type"] for item in risks} == {"risk"}
    assert {item["status"] for item in risks} == {"evidence_verified"}
    # axis 는 required(omission)·forbidden(commission) 에만 붙는다. 위험 신호에
    # axis 가 생기면 판정 축이 있다는 뜻이라 경보 전용이라는 성격과 어긋난다.
    assert not [item for item in risks if item.get("axis")]


def test_loan_third_party_repayment_risk_uses_current_article_20(bundles) -> None:
    item = next(item for item in bundles["loan"]["items"] if item["code"] == "LOAN-RSK-001")
    assert item["legal_basis"][0]["article"] == "제20조"


def test_exact_span_counter_detects_real_duplicate() -> None:
    pdf = paths.docs_dir(REPO_ROOT) / "01_금융소비자보호법.pdf"
    assert count_exact_span(pdf, "금융소비자", 11) > 1


def test_ambiguous_span_routes_to_manual_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("rulepack.pipeline.count_exact_span", lambda *_: 2)
    bundle = build_product_bundle(REPO_ROOT, "deposit", RULES, tmp_path / "ambiguous")
    ambiguous = [item for item in bundle["items"] if item["reason_code"] == "evidence_ambiguous"]
    assert ambiguous
    assert {item["status"] for item in ambiguous} == {"review_required"}


def test_compile_refuses_missing_approval_unverified_and_stale_source(
    bundles, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RULEPACK_APPROVAL_HMAC_KEY", TEST_APPROVAL_KEY)
    with pytest.raises(CompileError, match="승인"):
        compile_pack(REPO_ROOT, bundles["deposit"], {}, "DEP-2026.08-v1")

    # 원천을 전부 현행본으로 갈아 실제 conflict 항목이 없어졌다(2026-08-30).
    # 규칙 자체는 지켜야 하므로 항목을 그 상태로 만들어 검사한다.
    stale = deepcopy(bundles["deposit"])
    target = next(item for item in stale["items"] if item["code"] == "DEP-PRO-001")
    target["freshness"] = "conflict"
    target["publication_blocker"] = "stale_source"
    with pytest.raises(CompileError, match="stale_source"):
        compile_pack(
            REPO_ROOT,
            stale,
            _approval(stale, "DEP-PRO-001", signed=True),
            "DEP-2026.08-v1",
        )


def test_approval_signature_and_digest_block_spoofing(
    bundles, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RULEPACK_APPROVAL_HMAC_KEY", TEST_APPROVAL_KEY)
    unsigned = _approval(bundles["deposit"], "DEP-INT-002")
    with pytest.raises(CompileError, match="서명"):
        compile_pack(REPO_ROOT, bundles["deposit"], unsigned, "DEP-2026.08-v1")

    approval = _approval(bundles["deposit"], "DEP-INT-002", signed=True)
    changed = deepcopy(bundles["deposit"])
    next(item for item in changed["items"] if item["code"] == "DEP-INT-002")["plain_language"] = [
        "바꿔치기"
    ]
    with pytest.raises(CompileError, match="승인 후"):
        compile_pack(REPO_ROOT, changed, approval, "DEP-2026.08-v1")

    duplicate = _approval(bundles["deposit"], "DEP-INT-002")
    duplicate["item_codes"] *= 2
    duplicate["approval_signature"] = approval_signature(duplicate, TEST_APPROVAL_KEY)
    with pytest.raises(CompileError, match="중복"):
        compile_pack(REPO_ROOT, bundles["deposit"], duplicate, "DEP-2026.08-v1")


def test_synthetic_compile_is_enveloped_and_cannot_publish(bundles, tmp_path: Path) -> None:
    envelope = compile_synthetic_pack(
        REPO_ROOT,
        bundles["deposit"],
        _approval(bundles["deposit"], "DEP-INT-002", "real-reviewer"),
        "DEP-2026.08-v1",
    )
    assert envelope["artifact_kind"] == "synthetic_dry_run"
    assert envelope["production_publishable"] is False
    with pytest.raises(CompileError, match="attestation"):
        publish_immutable(envelope, tmp_path)
    with pytest.raises(CompileError, match="attestation"):
        publish_immutable(envelope["pack"], tmp_path)


def test_confirmed_signed_approval_compiles_and_publish_is_immutable(
    bundles, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _without_publication_blocker(bundles["deposit"], "DEP-INT-002")
    monkeypatch.setenv("RULEPACK_APPROVAL_HMAC_KEY", TEST_APPROVAL_KEY)
    monkeypatch.setattr(
        "rulepack.compiler._load_source_audit", lambda _: _confirmed_audit(bundle, "DEP-INT-002")
    )
    compiled = compile_pack(
        REPO_ROOT, bundle, _approval(bundle, "DEP-INT-002", signed=True), "DEP-2026.08-v1"
    )
    assert publish_immutable(compiled, tmp_path) == "created"
    assert publish_immutable(compiled, tmp_path) == "no_op"

    changed_bundle = deepcopy(bundle)
    changed_bundle["product"]["name"] = "다른 이름"
    changed = compile_pack(
        REPO_ROOT,
        changed_bundle,
        _approval(changed_bundle, "DEP-INT-002", signed=True),
        "DEP-2026.08-v1",
    )
    with pytest.raises(CompileError, match="다른 내용"):
        publish_immutable(changed, tmp_path)

    with pytest.raises(CompileError, match="schema"):
        compile_pack(REPO_ROOT, bundle, _approval(bundle, "DEP-INT-002", signed=True), "../escape")


def test_real_confirmed_legal_candidate_compiles_without_audit_stub(
    bundles, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = bundles["deposit"]
    monkeypatch.setenv("RULEPACK_APPROVAL_HMAC_KEY", TEST_APPROVAL_KEY)

    compiled = compile_pack(
        REPO_ROOT,
        bundle,
        _approval(bundle, "DEP-BAN-001", signed=True),
        "DEP-2026.08-v10",
    )

    assert [item["code"] for item in compiled["pack"]["items"]] == ["DEP-BAN-001"]


def test_confirmed_audit_must_reference_candidate_evidence_source(
    bundles, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = bundles["deposit"]
    unrelated = next(
        source for source in bundle["sources"] if source["doc_id"] == "03_예금거래기본약관"
    )
    wrong_audit = {
        "default": {"status": "unverified"},
        "candidates": {
            "DEP-BAN-001": {
                "status": "confirmed",
                "source_doc_id": unrelated["doc_id"],
                "source_sha256": unrelated["sha256"],
            }
        },
    }
    monkeypatch.setenv("RULEPACK_APPROVAL_HMAC_KEY", TEST_APPROVAL_KEY)
    monkeypatch.setattr("rulepack.compiler._load_source_audit", lambda _: wrong_audit)

    with pytest.raises(CompileError, match="source_audit_candidate_mismatch"):
        compile_pack(
            REPO_ROOT, bundle, _approval(bundle, "DEP-BAN-001", signed=True), "DEP-2026.08-v11"
        )


def test_source_refresh_classifies_every_non_fixture_candidate() -> None:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    audit = json.loads(
        (paths.config_dir(REPO_ROOT) / "source_audit.json").read_text(encoding="utf-8")
    )
    candidate_codes = {
        item["code"]
        for items in rules["products"].values()
        for item in items
        if "-REJ-" not in item["code"]
    }

    assert candidate_codes == set(audit["candidates"])
    status_counts = {
        status: sum(record["status"] == status for record in audit["candidates"].values())
        for status in ("confirmed", "unverified", "conflict")
    }
    # 감사 기록은 시점마다 새 파일로 쌓인다. 요약이 맞아야 하는 대상은 늘 최신본이다.
    latest = sorted(paths.default_artifacts_dir(REPO_ROOT).glob("source_refresh_*.json"))[-1]
    refresh = json.loads(latest.read_text(encoding="utf-8"))
    assert refresh["candidate_summary"] == {
        **status_counts,
        "excluded_negative_fixtures": 2,
    }


def _items_from(bundles, doc_id: str) -> list[dict]:
    return [
        item
        for bundle in bundles.values()
        for item in bundle["items"]
        if item["evidence"]["doc_id"] == doc_id and "-REJ-" not in item["code"]
    ]


def test_current_sources_have_no_publication_blockers(bundles) -> None:
    """원천을 전부 현행본으로 갈았으므로 상품 문서 기반 항목이 막히면 안 된다.

    2026-08-30 에 정기예금 설명서를 심의 유효기간 내 현행본(1억원 한도 반영)으로
    교체하며 마지막 차단이 풀렸다. 감사 갱신을 빠뜨리거나 원천을 되돌리면
    `source_audit_hash_mismatch` 로 다시 막히고 여기서 잡힌다.
    """
    for doc_id in ("05_상품설명서_정기예금", "06_상품설명서_가계대출"):
        items = _items_from(bundles, doc_id)
        assert items, f"{doc_id} 를 근거로 쓰는 항목이 없음"
        blocked = [i["code"] for i in items if i.get("publication_blocker")]
        assert not blocked, f"{doc_id}: 아직 막힌 항목 {blocked}"
        assert {i["freshness"] for i in items} == {"confirmed"}


def test_compile_revalidates_tampered_bbox_numeric_value_unit_condition_and_doc_id(bundles) -> None:
    for field, value, message in (
        ("value", "999", "라벨·값"),
        ("unit", "개월", "라벨·값"),
        ("condition", "무관한 조건", "조건"),
    ):
        changed = deepcopy(bundles["deposit"])
        item = next(item for item in changed["items"] if item["code"] == "DEP-PRO-001")
        item["numeric_facts"][0][field] = value
        with pytest.raises(CompileError, match=message):
            compile_synthetic_pack(
                REPO_ROOT,
                changed,
                _approval(changed, "DEP-PRO-001", "synthetic-reviewer"),
                "DEP-2026.08-v2",
            )

    bbox_changed = deepcopy(bundles["deposit"])
    item = next(item for item in bbox_changed["items"] if item["code"] == "DEP-LIM-001")
    item["evidence"]["bbox"] = [0, 0, 1, 1]
    with pytest.raises(CompileError, match="bbox"):
        compile_synthetic_pack(
            REPO_ROOT,
            bbox_changed,
            _approval(bbox_changed, "DEP-LIM-001", "synthetic-reviewer"),
            "DEP-2026.08-v2",
        )

    source_changed = deepcopy(bundles["deposit"])
    item = next(item for item in source_changed["items"] if item["code"] == "DEP-INT-002")
    item["evidence"]["doc_id"] = "../outside"
    with pytest.raises(CompileError, match="출처 없는 doc_id"):
        compile_synthetic_pack(
            REPO_ROOT,
            source_changed,
            _approval(source_changed, "DEP-INT-002", "synthetic-reviewer"),
            "DEP-2026.08-v2",
        )


def test_new_version_keeps_code_for_same_semantic_item(
    bundles, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _without_publication_blocker(bundles["deposit"], "DEP-INT-002")
    monkeypatch.setenv("RULEPACK_APPROVAL_HMAC_KEY", TEST_APPROVAL_KEY)
    monkeypatch.setattr(
        "rulepack.compiler._load_source_audit", lambda _: _confirmed_audit(bundle, "DEP-INT-002")
    )
    first = compile_pack(
        REPO_ROOT, bundle, _approval(bundle, "DEP-INT-002", signed=True), "DEP-2026.08-v1"
    )
    assert publish_immutable(first, tmp_path) == "created"

    changed_bundle = deepcopy(bundle)
    item = next(item for item in changed_bundle["items"] if item["code"] == "DEP-INT-002")
    item["code"] = "DEP-INT-999"
    changed_approval = _approval(changed_bundle, "DEP-INT-999", signed=True)
    monkeypatch.setattr(
        "rulepack.compiler._load_source_audit",
        lambda _: _confirmed_audit(changed_bundle, "DEP-INT-999"),
    )
    changed = compile_pack(REPO_ROOT, changed_bundle, changed_approval, "DEP-2026.08-v2")
    with pytest.raises(CompileError, match="code"):
        publish_immutable(changed, tmp_path)


def test_failed_adapter_item_does_not_contaminate_batch(tmp_path: Path) -> None:
    class PartiallyFailingAdapter:
        model = "partial-failure-test"

        def extract(self, prompt: str, schema: dict) -> dict:
            del schema
            payload = json.loads(prompt)
            candidate = payload["candidate"]
            if candidate["code"] == "DEP-INT-002":
                return {}
            return candidate

    bundle = build_product_bundle(
        REPO_ROOT, "deposit", RULES, tmp_path / "partial", PartiallyFailingAdapter()
    )
    failed = next(item for item in bundle["items"] if item["code"] == "DEP-INT-002")
    succeeded = next(item for item in bundle["items"] if item["code"] == "DEP-INT-001")
    assert failed["status"] == "review_required"
    assert failed["reason_code"] == "llm_extraction_failed"
    assert succeeded["status"] == "evidence_verified"


@pytest.mark.parametrize("body", [b'{"choices":[]}', b"\xff"])
def test_openai_adapter_converts_malformed_provider_response_to_adapter_error(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self) -> bytes:
            return body

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-logged")
    monkeypatch.setattr(
        "rulepack.adapters.urllib.request.urlopen", lambda *_args, **_kwargs: Response()
    )
    adapter = OpenAICompatibleAdapter(
        "https://example.invalid/v1/chat/completions", "test-model", max_attempts=1
    )
    with pytest.raises(AdapterError, match="구조화 후보 추출 실패"):
        adapter.extract("prompt", {"type": "object"})


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ('java version "1.8.0_402"', 8),
        ('openjdk version "11.0.24"', 11),
        ('openjdk version "17.0.20"', 17),
    ],
)
def test_java_major_parser(output: str, expected: int) -> None:
    assert _java_major(output) == expected


@pytest.mark.parametrize("output", ['java version "1.8.0_402"', 'openjdk version "11.0.24"'])
def test_strict_java_gate_rejects_versions_below_17(output: str) -> None:
    with pytest.raises(RuntimeError, match="Java 17"):
        _require_java17(output)


def test_candidate_evidence_from_adapter_is_the_value_p4_checks(tmp_path: Path) -> None:
    class AlteredEvidenceAdapter:
        model = "altered-evidence-test"

        def extract(self, prompt: str, schema: dict) -> dict:
            del schema
            candidate = json.loads(prompt)["candidate"]
            if candidate["code"] == "DEP-INT-002":
                candidate["evidence"]["span"] = "모델이 만든 원문에 없는 인용"
            return candidate

    bundle = build_product_bundle(
        REPO_ROOT, "deposit", RULES, tmp_path / "altered", AlteredEvidenceAdapter()
    )
    altered = next(item for item in bundle["items"] if item["code"] == "DEP-INT-002")
    assert altered["status"] == "rejected"
    assert altered["reason_code"] == "evidence_not_found_or_page_mismatch"


def test_candidate_must_link_to_a_chunk_that_was_in_its_prompt(tmp_path: Path) -> None:
    class WrongChunkAdapter:
        model = "wrong-chunk-test"

        def extract(self, prompt: str, schema: dict) -> dict:
            del schema
            candidate = json.loads(prompt)["candidate"]
            if candidate["code"] == "DEP-INT-002":
                candidate["source_chunk_id"] = "not-in-prompt"
            return candidate

    bundle = build_product_bundle(
        REPO_ROOT, "deposit", RULES, tmp_path / "wrong-chunk", WrongChunkAdapter()
    )
    altered = next(item for item in bundle["items"] if item["code"] == "DEP-INT-002")
    assert altered["status"] == "review_required"
    assert altered["reason_code"] == "candidate_chunk_mismatch"


def test_cli_connects_approved_compile_and_immutable_publish(
    bundles, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _without_publication_blocker(bundles["deposit"], "DEP-INT-002")
    monkeypatch.setenv("RULEPACK_APPROVAL_HMAC_KEY", TEST_APPROVAL_KEY)
    monkeypatch.setattr(
        "rulepack.compiler._load_source_audit", lambda _: _confirmed_audit(bundle, "DEP-INT-002")
    )
    approval = _approval(bundle, "DEP-INT-002", signed=True)
    bundle_path = tmp_path / "bundle.json"
    approval_path = tmp_path / "approval.json"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    approval_path.write_text(json.dumps(approval, ensure_ascii=False), encoding="utf-8")

    common = [
        "--repo-root",
        str(REPO_ROOT),
        "--output",
        str(tmp_path / "published"),
        "--bundle",
        str(bundle_path),
        "--approval",
        str(approval_path),
        "--version",
        "DEP-2026.08-v9",
    ]
    assert main(["compile", *common]) == 0
    assert main(["publish", *common]) == 0
    assert (tmp_path / "published" / "compiled_DEP-2026.08-v9.json").is_file()
    assert (tmp_path / "published" / "rulepack_DEP-2026.08-v9.json").is_file()


def test_run_manifest_has_no_unmapped_source_ids() -> None:
    run = build_run_manifest(REPO_ROOT)
    known = {source.doc_id for source in run.sources}
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    used = {rule["doc_id"] for items in rules["products"].values() for rule in items}
    assert used <= known


def test_status_doc_matches_actual_counts(bundles) -> None:
    """`docs/STATUS.md` 의 판정 표가 실제 build 결과와 같아야 한다.

    문서의 숫자를 손으로 적으면 코드가 바뀔 때마다 조용히 어긋난다. 낡은 문서는
    틀린 정보보다 나쁘므로 기계가 대조한다 (2026-08-29).
    """
    doc = (REPO_ROOT / "back" / "rulepack" / "docs" / "STATUS.md").read_text(encoding="utf-8")

    for product, label in (("deposit", "예금 신규"), ("loan", "신용대출")):
        items = bundles[product]["items"]
        actual = (
            sum(
                1
                for i in items
                if i["status"] == "evidence_verified" and not i.get("publication_blocker")
            ),
            sum(1 for i in items if i["status"] == "review_required"),
            sum(1 for i in items if i.get("publication_blocker")),
            sum(1 for i in items if i["status"] == "rejected"),
        )
        row = re.search(rf"\| {label} \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|", doc)
        assert row, f"STATUS.md 에 {label} 행이 없음"
        assert tuple(int(g) for g in row.groups()) == actual, f"{label} 판정 표가 실물과 다름"


def test_item_type_matches_who_the_article_binds(bundles) -> None:
    """항목 type 은 근거 조문이 누구를 구속하는지와 맞아야 한다.

    `forbidden` 은 은행원 발화, `risk` 는 고객 발화다. 뒤집히면 둘 중 하나가
    난다. 은행원의 위반이 경보로만 처리되어 판정에서 빠지거나, 고객이 한 말이
    은행원의 위반으로 표시되어 P6 를 어긴다.

    금소법 제20조는 "금융상품판매업자등은 ... 해서는 아니 된다" 로 은행원을
    구속한다. 예금거래기본약관 제6조는 "거래처는 ... 할 수 있다" 로 고객의
    행위를 적는다. 실제로 `LOAN-RSK-001` 이 제20조를 근거로 두고 `risk` 로
    분류돼 있었다 (2026-08-30).
    """
    은행원_구속 = {("금융소비자보호법", "제20조"), ("금융소비자보호법", "제21조")}
    고객_행위 = {("예금거래기본약관", "제6조")}

    for bundle in bundles.values():
        for item in bundle["items"]:
            basis = {(b["law"], b["article"]) for b in item["legal_basis"]}
            if basis & 은행원_구속:
                assert item["type"] != "risk", (
                    f"{item['code']}: 은행원을 구속하는 조문인데 고객 발화(risk)로 분류됨"
                )
            if basis & 고객_행위 and item["type"] == "risk":
                assert not item.get("axis"), f"{item['code']}: risk 에 axis 가 붙음"


def test_product_list_comes_from_config_not_code() -> None:
    """상품 목록의 진실 원천은 `config/products.json` 이다.

    코드에 박아 두면 상품을 늘릴 때 설정과 코드를 둘 다 고쳐야 하고, 한쪽만
    고치면 조용히 빠진다. 실제로 `cli.py` 가 `("deposit", "loan")` 을 박고
    있었다 (2026-08-30).
    """
    from rulepack.cli import _products

    config = json.loads((paths.config_dir(REPO_ROOT) / "products.json").read_text(encoding="utf-8"))
    assert _products(REPO_ROOT) == sorted(config)


def test_config_mismatch_says_which_file(tmp_path: Path) -> None:
    """상품 설정 두 개가 어긋나면 어느 파일이 빠졌는지 말해야 한다.

    `products.json` 에만 있고 `candidate_rules.json` 에 규칙이 없으면 전에는
    맨 KeyError 로 죽어 원인을 알 수 없었다.
    """
    from rulepack.pipeline import PipelineError, build_product_bundle

    rules = paths.config_dir(REPO_ROOT) / "candidate_rules.json"
    with pytest.raises(PipelineError, match="products.json 에 없는 상품"):
        build_product_bundle(REPO_ROOT, "nonexistent", rules, tmp_path / "x")


def test_freshness_gate_reads_audit_not_bundle() -> None:
    """최신성 판정은 번들이 아니라 `source_audit.json` 을 본다.

    번들의 `freshness` 를 손대도 발행이 열리면 안 된다. 감사 기록이 진실 원천이고
    번들은 그것을 옮겨 적은 사본이다. 2026-08-30 에 원천을 전부 현행본으로 갈아
    실제 `unverified` 항목이 없어졌으므로 감사를 직접 만들어 검사한다.
    """
    from rulepack.compiler import _verify_confirmed_freshness

    sources = {"05_상품설명서_정기예금": type("S", (), {"sha256": "abc"})()}

    with pytest.raises(CompileError, match="unverified_source"):
        _verify_confirmed_freshness("DEP-INT-002", "05_상품설명서_정기예금", sources, {})

    audit = {
        "candidates": {
            "DEP-INT-002": {
                "status": "unverified",
                "source_doc_id": "05_상품설명서_정기예금",
                "source_sha256": "abc",
            }
        }
    }
    with pytest.raises(CompileError, match="unverified_source"):
        _verify_confirmed_freshness("DEP-INT-002", "05_상품설명서_정기예금", sources, audit)

    # 감사가 confirmed 여도 원천 해시가 어긋나면 막는다.
    audit["candidates"]["DEP-INT-002"]["status"] = "confirmed"
    audit["candidates"]["DEP-INT-002"]["source_sha256"] = "다른해시"
    with pytest.raises(CompileError, match="source_audit_hash_mismatch"):
        _verify_confirmed_freshness("DEP-INT-002", "05_상품설명서_정기예금", sources, audit)


def test_pack_carries_l1_patterns_and_jargon_terms_from_config(bundles) -> None:
    """L1 패턴과 용어 목록은 설정에서 와서 팩까지 실려야 한다.

    둘 다 컴파일러가 조용히 빈 값으로 뭉갤 수 있는 자리다. 실제로 `l1_patterns`
    는 `result["l1_patterns"] = []` 로 고정돼 있어, 설정에 정규식을 아무리 적어도
    팩에는 안 실렸다. 그러면 L1(정규식) 층이 통째로 놀고 모든 판정이 L2·L3 로
    내려가 지연과 비용만 늘어난다. 빈 값은 예외를 내지 않으므로 테스트로만 잡힌다.
    """
    envelope = compile_synthetic_pack(
        REPO_ROOT,
        bundles["deposit"],
        _approval(bundles["deposit"], "DEP-INT-002", "real-reviewer"),
        "DEP-2026.08-v1",
    )
    pack = envelope["pack"]

    products = json.loads(
        (paths.config_dir(REPO_ROOT) / "products.json").read_text(encoding="utf-8")
    )
    assert pack["jargon_terms"] == products["deposit"]["jargon_terms"]
    assert pack["jargon_terms"], "용어 밀도 게이지가 셀 대상이 하나도 없음"

    from_bundle = {i["code"]: i.get("l1_patterns", []) for i in bundles["deposit"]["items"]}
    carried = {i["code"]: i["l1_patterns"] for i in pack["items"] if i["l1_patterns"]}
    assert carried, "L1 판정이 쓸 패턴이 팩에 하나도 안 실렸음"
    for code, patterns in carried.items():
        assert patterns == from_bundle[code]
