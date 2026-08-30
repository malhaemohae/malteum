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
    python scripts/load_pack.py <compile envelope> [--replace] [--dry-run] [--unsigned]
    APP_DATABASE_URL 로 접속 대상, RULEPACK_APPROVAL_HMAC_KEY 로 서명 검증키를 준다.
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

from rulepack.compiler import CompileError, verified_pack  # noqa: E402
from rulepack.embedding import (  # noqa: E402
    DeterministicFakeEmbedding,
    E5SmallEmbedding,
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


def model_for(pack: dict[str, Any]) -> EmbeddingModel:
    """팩이 적은 모델 이름으로 구현을 고른다.

    팩마다 다른 모델로 만들어졌을 수 있고, 적재는 그것을 그대로 재현해야 한다.
    모르는 이름이면 멈춘다. 아무 구현으로나 벡터를 만들면 팩이 말하는 것과 다른
    값이 DB 에 들어간다.
    """
    declared = pack["embedding"]
    for candidate in (E5SmallEmbedding(), DeterministicFakeEmbedding(dim=declared["dim"])):
        if candidate.name == declared["model"]:
            return candidate
    raise LoadError(f"모르는 임베딩 모델: {declared['model']}. 구현을 먼저 붙여야 함")


def unwrap(document: dict[str, Any], *, allow_unsigned: bool = False) -> dict[str, Any]:
    """envelope 의 서명을 검증하고 팩을 꺼낸다.

    `compile` 산출물은 attestation 이 붙은 envelope 이고 팩은 그 안에 있다.
    `publish` 가 낸 `rulepack_<version>.json` 은 팩 본문만이라 서명이 없다.
    그것을 그대로 받으면 발행 뒤 DB 에 넣기 전까지의 구간에서 내용을 고쳐도
    막을 방법이 없으므로, 서명 없는 입력은 `--unsigned` 를 명시해야 들어간다.

    dry-run envelope 은 `production_publishable` 이 거짓이라 여기서 막는다.
    """
    if "pack" not in document:
        if not allow_unsigned:
            raise LoadError(
                "서명 없는 팩임. `compile` 이 낸 envelope(`compiled_<version>.json`)을 주거나, "
                "무결성 검증을 건너뛰려면 --unsigned 를 명시해야 함"
            )
        return document
    if not document.get("production_publishable"):
        kind = document.get("artifact_kind", "unknown")
        raise LoadError(f"운영 발행물이 아님({kind}). 적재하려면 compile 산출물이어야 함")
    try:
        return verified_pack(document)
    except CompileError as exc:
        raise LoadError(f"팩 무결성 검증 실패: {exc}") from exc


def rows(
    pack: dict[str, Any], model: EmbeddingModel, *, encode: bool = True
) -> tuple[tuple, list[tuple]]:
    """팩을 `rule_packs` 한 행과 `pack_embeddings` 여러 행으로 편다.

    `rule_packs.doc` 이 정본이고 나머지 열은 조회용 사본이다(`db/SCHEMA.md` 2절).
    항목을 열로 펼치지 않는 이유가 둘 있다. M2 가 `SELECT doc` 한 줄로 팩을 그대로
    돌려받아야 하고, 열로 펼치면 `published_at` 이 timestamptz 를 왕복하며 표기가
    바뀌어(`2026-08-30T00:00:00Z` → `2026-08-30 00:00:00+00`) `pack_sha256` 대조가
    깨진다. JSONB 는 바이트를 보존한다.

    임베딩은 항목 하나당 여러 행이 된다. 금지·위험 예시와 쉬운 말이 각각 검색면이
    되어야 L2 가 발화를 넓게 잡는다. `jargon_terms` 는 넣지 않는다. 용어 밀도
    게이지는 목록 대조로만 세므로 벡터가 필요 없고, 팩 전역이라 붙일 `item_code`
    도 없다.
    """
    declared = pack["embedding"]
    if declared["model"] != model.name or declared["dim"] != model.dim:
        raise LoadError(
            f"팩이 적은 임베딩({declared['model']}/{declared['dim']})과 "
            f"지금 쓰는 구현({model.name}/{model.dim})이 다름. 팩을 만든 모델로 넣어야 함"
        )

    product = pack["product"]
    head = (
        pack["pack_version"],
        product["code"],
        product["name"],
        product["category"],
        pack["published_at"],
        pack.get("published_by"),
        declared["model"],
        declared["dim"],
        json.dumps(pack, ensure_ascii=False),
    )

    slots: list[tuple[str, str | None, str, int, str]] = []
    for item in pack["items"]:
        code, embedding_id = item["code"], item.get("embedding_id")
        slots.append((code, embedding_id, "item", 0, embedding_text(item)))
        for key, source in (
            ("forbidden_examples", "forbidden_example"),
            ("risk_examples", "risk_example"),
            ("plain_language", "plain_language"),
        ):
            for ordinal, body in enumerate(item.get(key) or []):
                slots.append((code, embedding_id, source, ordinal, str(body)))

    # dry-run 은 행 수만 세므로 모델(약 0.5GB)을 올리지 않는다. 그때 벡터 자리는
    # None 이라 그 결과를 DB 에 넣으면 안 된다.
    texts = [slot[4] for slot in slots]
    vectors = model.encode(texts) if (texts and encode) else [None] * len(texts)
    embeddings = [
        (
            pack["pack_version"],
            code,
            embedding_id,
            source,
            ordinal,
            body,
            vector,
            model.name,
            model.dim,
        )
        for (code, embedding_id, source, ordinal, body), vector in zip(slots, vectors, strict=True)
    ]
    return head, embeddings


_HEAD_SQL = (
    "insert into rule_packs (pack_version, product_code, product_name, product_category,"
    " published_at, published_by, embedding_model, embedding_dim, doc)"
    " values (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_EMBEDDING_SQL = (
    "insert into pack_embeddings (pack_version, item_code, embedding_id, source, ordinal,"
    " body_text, embedding, model, dim) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def load(pack: dict[str, Any], dsn: str, model: EmbeddingModel, replace: bool = False) -> int:
    """팩 한 벌을 넣는다. 같은 버전이 있으면 `replace` 없이는 거절한다."""
    head, embeddings = rows(pack, model)
    version = pack["pack_version"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("select 1 from rule_packs where pack_version = %s", (version,))
        if cur.fetchone():
            if not replace:
                raise LoadError(f"{version} 이 이미 있음. 팩은 불변이라 새 버전을 내는 것이 원칙")
            # pack_embeddings 의 FK 가 CASCADE 라 머리만 지우면 따라 지워진다.
            cur.execute("delete from rule_packs where pack_version = %s", (version,))
        cur.execute(_HEAD_SQL, head)
        cur.executemany(_EMBEDDING_SQL, embeddings)
        conn.commit()
    return len(embeddings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="팩 JSON 을 postgres 에 적재")
    parser.add_argument("pack", type=Path, help="compile 산출물 또는 팩 JSON")
    parser.add_argument(
        "--replace", action="store_true", help="같은 버전이 있으면 지우고 다시 넣음"
    )
    parser.add_argument("--dry-run", action="store_true", help="행만 만들어 보고 DB 는 안 건드림")
    parser.add_argument(
        "--unsigned",
        action="store_true",
        help="서명 없는 팩 본문을 받아들임. 무결성 검증을 건너뛰므로 개발용",
    )
    args = parser.parse_args(argv)

    document = json.loads(args.pack.read_text(encoding="utf-8"))
    pack = unwrap(document, allow_unsigned=args.unsigned)
    model = model_for(pack)

    if args.dry_run:
        _, embeddings = rows(pack, model, encode=False)
        print(
            json.dumps(
                {
                    "pack_version": pack["pack_version"],
                    "items": len(pack["items"]),
                    "embeddings": len(embeddings),
                    "dry_run": True,
                },
                ensure_ascii=False,
            )
        )
        return 0

    embedding_count = load(pack, dsn_from_env(), model, replace=args.replace)
    print(
        json.dumps(
            {
                "pack_version": pack["pack_version"],
                "items": len(pack["items"]),
                "embeddings": embedding_count,
                "loaded": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
