"""임베딩 어댑터와 팩 적재.

DB 가 필요한 검사는 `psycopg` 로 붙어 보고 실패하면 건너뛴다. CI 에는 postgres
서비스가 없고, 로컬은 `docker compose up -d db` 로 띄운다.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "back" / "scripts"))

from rulepack.embedding import (  # noqa: E402
    DeterministicFakeEmbedding,
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
    url = os.environ.get("APP_DATABASE_URL", "postgresql://app:app@localhost:5432/app")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def conn():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(_dsn(), connect_timeout=3) as connection:
            with connection.cursor() as cur:
                cur.execute("select to_regclass('pack')")
                if cur.fetchone()[0] is None:
                    pytest.skip("pack 테이블 없음. alembic upgrade head 가 필요함")
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
    """적재한 팩을 다시 읽어 같은 값인지 본다."""
    from load_pack import load

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
    try:
        assert load(pack, _dsn(), model, replace=True) == 1
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute(
                "select product_category, embedding_model from pack where pack_version = %s",
                (pack["pack_version"],),
            )
            assert cur.fetchone() == ("deposit", "deterministic-fake")
            cur.execute(
                "select type, axis, risk_examples, numeric_facts from pack_item"
                " where pack_version = %s",
                (pack["pack_version"],),
            )
            row = cur.fetchone()
            assert row[0] == "risk"
            assert row[1] is None
            assert row[2] == ["대신 입금할게요"]
            # 팩에 없던 필드는 JSON null 이 아니라 SQL null 이어야 한다.
            assert row[3] is None
            cur.execute(
                "select vector_dims(vector) from item_embedding where pack_version = %s",
                (pack["pack_version"],),
            )
            assert cur.fetchone()[0] == model.dim
    finally:
        with conn.cursor() as cur:
            for table in ("item_embedding", "pack_item", "pack"):
                cur.execute(f"delete from {table} where pack_version = %s", (pack["pack_version"],))
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
            for table in ("item_embedding", "pack_item", "pack"):
                cur.execute(f"delete from {table} where pack_version = %s", (pack["pack_version"],))
            conn.commit()
