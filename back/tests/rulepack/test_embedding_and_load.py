"""임베딩 어댑터와 팩 적재.

DB 가 필요한 검사는 `psycopg` 로 붙어 보고 실패하면 건너뛴다. CI 에는 postgres
서비스가 없고, 로컬은 `docker compose up -d db` 로 띄운다.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

from rulepack.embedding import (  # noqa: E402
    DeterministicFakeEmbedding,
    E5SmallEmbedding,
    EmbeddingError,
    embedding_text,
)


def test_fake_embedding_is_deterministic_and_unit_length() -> None:
    """같은 입력에 늘 같은 값이 나와야 `verify --strict` 의 결정성 검사를 통과한다."""
    model = DeterministicFakeEmbedding()
    first = model.encode(["연체이자율", "중도상환수수료"])
    second = model.encode(["연체이자율", "중도상환수수료"])

    assert first == second
    assert [len(v) for v in first] == [model.dim, model.dim]
    assert first[0] != first[1]
    for vector in first:
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, rel_tol=1e-9)


def test_fake_embedding_rejects_bad_dim() -> None:
    with pytest.raises(EmbeddingError):
        DeterministicFakeEmbedding(dim=0)


def test_embedding_text_excludes_legal_span() -> None:
    """근거 원문은 넣지 않는다. 법령 문장은 상담 발화와 멀어 검색을 흐린다."""
    item = {
        "name": "연체이자율",
        "requirement_elements": ["대출이자율"],
        "plain_language": ["연체하면 가산금리가 붙습니다."],
        "evidence": {"span": "◉ 연체이자율은 [대출이자율 + 연체가산이자율]로 적용합니다."},
    }
    text = embedding_text(item)

    assert "연체이자율" in text
    assert "가산금리가 붙습니다" in text
    assert "◉" not in text


def test_pack_records_the_model_that_made_it(tmp_path: Path) -> None:
    """팩의 `embedding` 은 실제로 벡터를 만든 구현을 적어야 한다.

    상수로 박아 두면 벡터를 만든 적도 없는 모델 이름이 팩에 남는다. 2026-08-29
    이전이 `intfloat/multilingual-e5-small` 을 그렇게 적고 있었다.
    """
    from rulepack import paths
    from rulepack.compiler import approval_digest, compile_synthetic_pack
    from rulepack.pipeline import build_product_bundle

    model = DeterministicFakeEmbedding(dim=8)
    rules = paths.config_dir(REPO_ROOT) / "candidate_rules.json"
    bundle = build_product_bundle(REPO_ROOT, "loan", rules, tmp_path / "loan")
    code = next(
        i["code"]
        for i in bundle["items"]
        if i["status"] == "evidence_verified" and not i.get("publication_blocker")
    )
    approval = {
        "approved_by": "t",
        "approved_at": "2026-08-29T00:00:00Z",
        "item_codes": [code],
        "bundle_sha256": approval_digest(bundle),
    }
    pack = compile_synthetic_pack(REPO_ROOT, bundle, approval, "LOAN-2026.08-v99", model)["pack"]

    assert pack["embedding"] == {"model": "deterministic-fake", "dim": 8, "normalized": True}
    assert pack["items"][0]["embedding_id"].startswith("fake:")


def _dsn() -> str:
    """`load()` 에 넘길 SQLAlchemy 접속 주소. 기본값을 두 곳에 적지 않는다."""
    from load_pack import dsn_from_env

    return dsn_from_env()


def _raw_dsn() -> str:
    """psycopg 로 직접 붙을 때. 드라이버 접미어를 모른다."""
    return _dsn().replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def conn():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(_raw_dsn(), connect_timeout=3) as connection:
            with connection.cursor() as cur:
                cur.execute("select to_regclass('rule_packs')")
                if cur.fetchone()[0] is None:
                    pytest.skip("rule_packs 테이블 없음. alembic upgrade head 가 필요함")
            yield connection
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"postgres 에 붙지 못함: {type(exc).__name__}")


def test_load_rejects_dry_run_envelope() -> None:
    """검증용 합성 팩이 운영 DB 로 들어가면 안 된다."""
    from load_pack import LoadError, unwrap

    with pytest.raises(LoadError, match="운영 발행물이 아님"):
        unwrap({"artifact_kind": "synthetic_dry_run", "production_publishable": False, "pack": {}})


def test_load_rejects_model_mismatch() -> None:
    """팩이 적은 모델과 다른 구현으로 벡터를 만들면 막는다."""
    from load_pack import LoadError, rows

    pack = {
        "pack_version": "LOAN-2026.08-v96",
        "schema_version": "1",
        "product": {"code": "P", "name": "n", "category": "loan"},
        "published_at": "2026-08-29T00:00:00Z",
        "embedding": {"model": "some-other-model", "dim": 384, "normalized": True},
        "sources": [],
        "items": [],
    }
    with pytest.raises(LoadError, match="다름"):
        rows(pack, DeterministicFakeEmbedding())


def test_load_pack_roundtrip(conn) -> None:
    """적재한 팩을 다시 읽어 한 글자도 안 달라졌는지 본다.

    `rule_packs.doc` 이 정본이다. 항목을 열로 펼쳐 담으면 `published_at` 이
    timestamptz 를 왕복하며 표기가 바뀌고(`...T00:00:00Z` → `... 00:00:00+00`)
    `pack_sha256` 대조가 깨진다. 2026-08-30 에 저장 스키마를 서버 쪽으로 통합한
    판단의 근거가 이것이라, 그 보장을 여기서 지킨다.
    """
    import hashlib

    from load_pack import load

    from rulepack.pipeline import canonical_json

    model = DeterministicFakeEmbedding(dim=8)
    pack = {
        "pack_version": "TEST-2026.08-v98",
        "schema_version": "1",
        "product": {"code": "T", "name": "테스트 상품", "category": "deposit"},
        "published_at": "2026-08-29T00:00:00Z",
        "published_by": "pytest",
        "embedding": {"model": model.name, "dim": model.dim, "normalized": True},
        "sources": [{"doc_id": "d", "title": "t", "publisher": "p", "snapshot_date": "2026-08-29"}],
        "items": [
            {
                "code": "T-RSK-001",
                "name": "위험 신호",
                "type": "risk",
                "requirement_elements": ["요건"],
                "legal_basis": [{"law": "법", "article": "제1조"}],
                "evidence": {"doc_id": "d", "page": 1, "span": "원문"},
                "risk_examples": ["대신 입금할게요"],
                "embedding_id": "fake:T-RSK-001",
                "approved_at": "2026-08-29T00:00:00Z",
            }
        ],
    }
    before = hashlib.sha256(canonical_json(pack).encode("utf-8")).hexdigest()
    try:
        # 항목 1행 + risk_examples 1행. 예시도 각각 검색면이 된다.
        assert load(pack, _dsn(), model, replace=True) == 2
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute(
                "select product_category, embedding_model, doc from rule_packs"
                " where pack_version = %s",
                (pack["pack_version"],),
            )
            category, embedding_model, doc = cur.fetchone()
            assert (category, embedding_model) == ("deposit", "deterministic-fake")
            assert hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest() == before
            assert doc["published_at"] == pack["published_at"]

            cur.execute(
                "select source, ordinal, body_text, vector_dims(embedding) from pack_embeddings"
                " where pack_version = %s order by source, ordinal",
                (pack["pack_version"],),
            )
            got = cur.fetchall()
            assert [(row[0], row[1]) for row in got] == [("item", 0), ("risk_example", 0)]
            assert got[1][2] == "대신 입금할게요"
            assert {row[3] for row in got} == {model.dim}
    finally:
        with conn.cursor() as cur:
            # pack_embeddings 의 FK 가 CASCADE 라 머리만 지우면 따라 지워진다.
            cur.execute("delete from rule_packs where pack_version = %s", (pack["pack_version"],))
            conn.commit()


def test_pack_is_immutable_without_replace(conn) -> None:
    """같은 버전을 두 번 넣으면 거절한다. 팩은 불변 발행물이다."""
    from load_pack import LoadError, load

    model = DeterministicFakeEmbedding(dim=4)
    pack = {
        "pack_version": "TEST-2026.08-v97",
        "schema_version": "1",
        "product": {"code": "T", "name": "n", "category": "loan"},
        "published_at": "2026-08-29T00:00:00Z",
        "embedding": {"model": model.name, "dim": model.dim, "normalized": True},
        "sources": [],
        "items": [],
    }
    try:
        load(pack, _dsn(), model)
        with pytest.raises(LoadError, match="이미 있음"):
            load(pack, _dsn(), model)
        load(pack, _dsn(), model, replace=True)
    finally:
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute("delete from rule_packs where pack_version = %s", (pack["pack_version"],))
            conn.commit()


def test_e5_declares_contract_values() -> None:
    """팩에 적히는 값이라 바뀌면 과거 팩과 어긋난다."""
    model = E5SmallEmbedding()

    assert model.name == "intfloat/multilingual-e5-small"
    assert model.dim == 384
    assert model.id_prefix == "e5"
    assert model.normalized is True


def test_e5_rejects_unknown_prefix() -> None:
    """E5 는 query·passage 접두어로 학습됐다. 다른 값은 학습 분포와 어긋난다."""
    with pytest.raises(EmbeddingError):
        E5SmallEmbedding(prefix="document")


def test_model_for_picks_by_declared_name() -> None:
    """팩이 적은 모델로 구현을 고른다. 아무 구현으로나 만들면 팩과 다른 값이 들어간다."""
    from load_pack import LoadError, model_for

    assert model_for(
        {"embedding": {"model": "intfloat/multilingual-e5-small", "dim": 384}}
    ).name == ("intfloat/multilingual-e5-small")
    assert model_for({"embedding": {"model": "deterministic-fake", "dim": 8}}).dim == 8
    with pytest.raises(LoadError, match="모르는 임베딩 모델"):
        model_for({"embedding": {"model": "some-future-api", "dim": 1536}})


def test_published_pack_is_readable_by_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3 가 발행한 팩을 M2 의 로더가 그대로 읽어야 한다.

    두 모듈은 서로의 코드를 모르고 `rulepack_<version>.json` 파일 이름 하나로
    만난다. 발행 쪽 이름이 바뀌면 읽는 쪽이 조용히 못 찾는다. `publish` 는
    이 세션 전까지 한 번도 실행된 적이 없었다 (2026-08-30).
    """
    from engine.adapters.pack_source.file import FilePackSource
    from engine.pack.loader import load_pack
    from rulepack import paths
    from rulepack.compiler import approval_digest, approval_signature, compile_pack
    from rulepack.pipeline import build_product_bundle

    key = "test-approval-key-that-is-at-least-32-bytes"
    monkeypatch.setenv("RULEPACK_APPROVAL_HMAC_KEY", key)
    rules = paths.config_dir(REPO_ROOT) / "candidate_rules.json"
    bundle = build_product_bundle(REPO_ROOT, "loan", rules, tmp_path / "work")
    codes = [
        i["code"]
        for i in bundle["items"]
        if i["status"] == "evidence_verified" and not i.get("publication_blocker")
    ]
    approval = {
        "approved_by": "pytest",
        "approved_at": "2026-08-30T00:00:00Z",
        "item_codes": codes,
        "bundle_sha256": approval_digest(bundle),
    }
    approval["approval_signature"] = approval_signature(approval, key)

    from rulepack.compiler import publish_immutable

    compiled = compile_pack(REPO_ROOT, bundle, approval, "LOAN-2026.08-v9")
    assert publish_immutable(compiled, tmp_path / "out") == "created"

    # 발행 쪽이 쓴 이름을 읽는 쪽이 그대로 찾는다.
    pack = load_pack(FilePackSource(tmp_path / "out"), "LOAN-2026.08-v9")
    assert len(pack.items) == len(codes)


def test_publish_rejects_non_production_artifact(tmp_path: Path) -> None:
    """검증용 dry-run 산출물은 발행되면 안 된다."""
    from rulepack.compiler import CompileError, publish_immutable

    with pytest.raises(CompileError, match="attestation"):
        publish_immutable(
            {"artifact_kind": "synthetic_dry_run", "production_publishable": False, "pack": {}},
            tmp_path / "out",
        )


def _signed_envelope(pack: dict, key: str) -> dict:
    """`compile` 이 내는 것과 같은 모양의 운영 envelope 을 만든다."""
    import hashlib
    import hmac

    from rulepack.pipeline import canonical_json

    pack_sha = hashlib.sha256(canonical_json(pack).encode("utf-8")).hexdigest()
    payload = {
        "artifact_kind": "production_compiled",
        "approval_signature": "approval-sig",
        "pack_sha256": pack_sha,
    }
    attestation = hmac.new(
        key.encode("utf-8"), canonical_json(payload).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        "artifact_kind": "production_compiled",
        "production_publishable": True,
        "approval_signature": "approval-sig",
        "pack_sha256": pack_sha,
        "compiler_attestation": attestation,
        "pack": pack,
    }


def test_load_rejects_unsigned_pack_and_tampered_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """적재도 발행과 같은 무결성 검사를 거쳐야 한다.

    `publish` 는 팩 본문만 파일로 쓴다. 그것을 그대로 적재하면 발행 시점부터
    DB 에 들어가기 전까지의 구간에서 금액 한 자리만 고쳐도 아무도 모른다.
    팩은 창구 판정의 기준이라 그 순간 시스템이 틀린 것을 가르치게 된다.
    """
    import json

    from load_pack import LoadError, unwrap

    key = "test-approval-key-that-is-at-least-32-bytes"
    monkeypatch.setenv("RULEPACK_APPROVAL_HMAC_KEY", key)
    pack = {
        "pack_version": "DEP-2026.08-v9",
        "product": {"code": "X", "name": "X", "category": "deposit"},
        "items": [{"code": "DEP-PRO-001", "plain_language": ["1억 원까지 보호됩니다."]}],
    }

    # 서명 없는 팩 본문은 명시적으로 허용해야만 들어간다.
    with pytest.raises(LoadError, match="서명 없는 팩"):
        unwrap(pack)
    assert unwrap(pack, allow_unsigned=True) == pack

    # 서명이 맞으면 팩을 그대로 돌려준다.
    envelope = _signed_envelope(pack, key)
    assert unwrap(envelope) == pack

    # 내용을 한 글자만 고쳐도 pack_sha256 대조에서 걸린다.
    tampered = json.loads(json.dumps(envelope, ensure_ascii=False))
    tampered["pack"]["items"][0]["plain_language"][0] = "5천만 원까지 보호됩니다."
    with pytest.raises(LoadError, match="무결성 검증 실패"):
        unwrap(tampered)

    # attestation 만 지워도 통과하면 안 된다.
    no_sig = json.loads(json.dumps(envelope, ensure_ascii=False))
    no_sig["compiler_attestation"] = ""
    with pytest.raises(LoadError, match="무결성 검증 실패"):
        unwrap(no_sig)


def test_load_rejects_pack_that_breaks_contract() -> None:
    """계약을 어긴 팩은 DB 에 들어가면 안 된다.

    `compile` 이 이미 검사하지만 그건 발행 시점 이야기다. 손으로 만든 팩이나 옛
    버전을 넣는 경로가 남아 있으므로 넣기 직전에 다시 본다. M1 의 `seed_pack.py`
    가 하던 검사를 흡수한 것 (2026-08-30).
    """
    import json

    from load_pack import LoadError, check_contract

    real = json.loads(
        (REPO_ROOT / "back" / "contracts" / "fixtures" / "rulepack_DEP-2026.08-v6.json").read_text(
            encoding="utf-8"
        )
    )
    check_contract(real)  # 발행된 팩은 통과한다

    with pytest.raises(LoadError, match="rulepack.schema.json"):
        check_contract({"pack_version": "BAD-2026.08-v1", "items": []})


def test_resolve_targets_published_packs_only(tmp_path: Path) -> None:
    """인자 없이 부르면 발행물 전부가 대상이다. compile 중간 산출물은 아니다."""
    from load_pack import resolve

    for name in ("rulepack_DEP-2026.08-v1.json", "rulepack_LOAN-2026.08-v1.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "compiled_DEP-2026.08-v1.json").write_text("{}", encoding="utf-8")

    assert [p.name for p in resolve(None, tmp_path)] == [
        "rulepack_DEP-2026.08-v1.json",
        "rulepack_LOAN-2026.08-v1.json",
    ]
    assert resolve("DEP-2026.08-v1", tmp_path) == [tmp_path / "rulepack_DEP-2026.08-v1.json"]
