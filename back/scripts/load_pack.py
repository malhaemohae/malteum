#!/usr/bin/env python3
"""발행된 팩 JSON 을 postgres 에 적재한다.

왜 REST 가 아니라 스크립트인가
    서버가 떠 있지 않아도 팩을 넣을 수 있어야 한다. 발행은 오프라인 배치이고
    상담 서버의 가동과 무관하다 (`back/rulepack/AGENTS.md`).

왜 ORM 모델을 안 쓰는가
    테이블 정의는 `server/database/entities/pack.py` 에 있지만, 발행 도구가
    상담 서버의 모델에 붙으면 두 배포가 한 몸이 된다. `scripts/` 는
    import-linter 의 `root_packages` 밖이라 린터가 막지는 않는다. 설계 의도로
    지키는 경계이고, 열이 바뀌면 이 파일도 같이 고쳐야 하는 대가를 진다.

멱등성
    팩은 불변 발행물이라 같은 `pack_version` 을 두 번 넣지 않는다. 이미 있으면
    기본적으로 거절하고, `--replace` 를 주면 지운 뒤 다시 넣는다. 조용히
    덮어쓰면 무엇이 들어 있는지 아무도 확신할 수 없게 된다.

사용
    python scripts/load_pack.py <팩 또는 envelope JSON> [--replace] [--dry-run]
    APP_DATABASE_URL 로 접속 대상을 바꾼다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rulepack.embedding import (  # noqa: E402
    DeterministicFakeEmbedding,
    EmbeddingModel,
    embedding_text,
)

DEFAULT_DSN = "postgresql://app:app@localhost:5432/app"


class LoadError(RuntimeError):
    """적재 실패."""


def dsn_from_env() -> str:
    """`APP_DATABASE_URL` 을 psycopg 가 읽는 형태로 바꾼다.

    server 설정은 SQLAlchemy 용이라 `postgresql+psycopg://` 로 시작한다.
    psycopg 는 드라이버 접미어를 모른다.
    """
    url = os.environ.get("APP_DATABASE_URL", DEFAULT_DSN)
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def unwrap(document: dict[str, Any]) -> dict[str, Any]:
    """envelope 이면 팩을 꺼낸다.

    `compile` 산출물은 attestation 이 붙은 envelope 이고 팩은 그 안에 있다.
    dry-run envelope 은 `production_publishable` 이 거짓이라 여기서 막는다.
    """
    if "pack" not in document:
        return document
    if not document.get("production_publishable"):
        kind = document.get("artifact_kind", "unknown")
        raise LoadError(f"운영 발행물이 아님({kind}). 적재하려면 compile 산출물이어야 함")
    return document["pack"]


def _jsonb(value: Any) -> str | None:
    """JSONB 열에 넣을 값. 팩에 없던 필드는 SQL null 로 남긴다.

    `json.dumps(None)` 은 문자열 `"null"` 이라 JSON null 로 저장된다. 그러면
    "그 필드가 없었다" 와 "값이 null 이었다" 를 나중에 구분할 수 없다.
    """
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def rows(
    pack: dict[str, Any], model: EmbeddingModel, *, encode: bool = True
) -> tuple[tuple, list[tuple], list[tuple]]:
    """팩을 테이블 세 벌의 행으로 편다."""
    declared = pack["embedding"]
    if declared["model"] != model.name or declared["dim"] != model.dim:
        raise LoadError(
            f"팩이 적은 임베딩({declared['model']}/{declared['dim']})과 "
            f"지금 쓰는 구현({model.name}/{model.dim})이 다름. 팩을 만든 모델로 넣어야 함"
        )

    product = pack["product"]
    head = (
        pack["pack_version"],
        str(pack["schema_version"]),
        product["code"],
        product["name"],
        product["category"],
        pack["published_at"],
        pack.get("published_by"),
        declared["model"],
        declared["dim"],
        declared.get("normalized", True),
        _jsonb(pack["sources"]),
        _jsonb(pack.get("jargon_terms", [])),
    )

    items: list[tuple] = []
    vectors: list[tuple] = []
    texts = [embedding_text(item) for item in pack["items"]]
    # dry-run 은 행 수만 세므로 모델(약 0.5GB)을 올리지 않는다. 그때 벡터 자리는
    # None 이라 그 결과를 DB 에 넣으면 안 된다.
    encoded = model.encode(texts) if (texts and encode) else [None] * len(texts)
    for item, vector in zip(pack["items"], encoded, strict=True):
        items.append(
            (
                pack["pack_version"],
                item["code"],
                item["name"],
                item["type"],
                item.get("axis"),
                _jsonb(item["requirement_elements"]),
                _jsonb(item["legal_basis"]),
                _jsonb(item["evidence"]),
                _jsonb(item.get("l1_patterns")),
                item.get("embedding_id"),
                _jsonb(item.get("plain_language")),
                _jsonb(item.get("numeric_facts")),
                _jsonb(item.get("documents_required")),
                _jsonb(item.get("forbidden_examples")),
                _jsonb(item.get("risk_examples")),
                item["approved_at"],
                item.get("approved_by"),
            )
        )
        if item.get("embedding_id"):
            vectors.append((pack["pack_version"], item["embedding_id"], vector))
    return head, items, vectors


def load(pack: dict[str, Any], dsn: str, model: EmbeddingModel, replace: bool = False) -> int:
    """한 트랜잭션으로 넣는다. 중간에 실패하면 아무것도 안 남는다."""
    head, items, vectors = rows(pack, model)
    version = pack["pack_version"]

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("select 1 from pack where pack_version = %s", (version,))
        if cur.fetchone():
            if not replace:
                raise LoadError(f"{version} 이 이미 있음. 팩은 불변이라 새 버전을 내는 것이 원칙")
            # FK 가 RESTRICT 라 자식부터 지운다.
            cur.execute("delete from item_embedding where pack_version = %s", (version,))
            cur.execute("delete from pack_item where pack_version = %s", (version,))
            cur.execute("delete from pack where pack_version = %s", (version,))

        cur.execute(
            "insert into pack (pack_version, schema_version, product_code, product_name,"
            " product_category, published_at, published_by, embedding_model, embedding_dim,"
            " embedding_normalized, sources, jargon_terms)"
            " values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            head,
        )
        cur.executemany(
            "insert into pack_item (pack_version, code, name, type, axis, requirement_elements,"
            " legal_basis, evidence, l1_patterns, embedding_id, plain_language, numeric_facts,"
            " documents_required, forbidden_examples, risk_examples, approved_at, approved_by)"
            " values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            items,
        )
        cur.executemany(
            "insert into item_embedding (pack_version, embedding_id, vector) values (%s,%s,%s)",
            [(v, eid, str(vec)) for v, eid, vec in vectors],
        )
        conn.commit()
    return len(items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="팩 JSON 을 postgres 에 적재")
    parser.add_argument("pack", type=Path, help="compile 산출물 또는 팩 JSON")
    parser.add_argument(
        "--replace", action="store_true", help="같은 버전이 있으면 지우고 다시 넣음"
    )
    parser.add_argument("--dry-run", action="store_true", help="행만 만들어 보고 DB 는 안 건드림")
    args = parser.parse_args(argv)

    document = json.loads(args.pack.read_text(encoding="utf-8"))
    pack = unwrap(document)
    model = DeterministicFakeEmbedding(dim=pack["embedding"]["dim"])

    if args.dry_run:
        _, items, vectors = rows(pack, model, encode=False)
        print(
            json.dumps(
                {
                    "pack_version": pack["pack_version"],
                    "items": len(items),
                    "vectors": len(vectors),
                    "dry_run": True,
                },
                ensure_ascii=False,
            )
        )
        return 0

    count = load(pack, dsn_from_env(), model, replace=args.replace)
    print(
        json.dumps(
            {"pack_version": pack["pack_version"], "items": count, "loaded": True},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
