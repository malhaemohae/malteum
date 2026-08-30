#!/usr/bin/env python3
"""발행된 팩 JSON 을 postgres 에 적재한다.

왜 REST 가 아니라 스크립트인가
    서버가 떠 있지 않아도 팩을 넣을 수 있어야 한다. 발행은 오프라인 배치이고
    상담 서버의 가동과 무관하다 (`back/rulepack/AGENTS.md`).

왜 M1 의 ORM 모델을 쓰는가
    테이블은 M1 이 소유한다(`server/database/entities/rulepack.py` · `db/SCHEMA.md`).
    열을 SQL 로 다시 적으면 계약이 늘 때 이 파일이 조용히 뒤처진다. nullable 열이
    추가되면 아무 테스트도 안 깨지고 그 열만 영원히 null 로 남는다. `scripts/` 는
    import-linter 의 `root_packages` 밖이라 이 import 는 경계를 어기지 않는다.
    대가는 이 스크립트가 `server` 패키지에 묶인다는 것인데, 발행 도구를 서버와
    따로 배포할 계획이 아직 없어 지금은 지불할 만하다 (2026-08-30).

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
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from rulepack.compiler import CompileError, verified_pack  # noqa: E402
from rulepack.embedding import (  # noqa: E402
    DeterministicFakeEmbedding,
    E5SmallEmbedding,
    EmbeddingModel,
    embedding_text,
)

# 테이블 정의는 M1 이 소유한다(`db/SCHEMA.md`). 열을 손으로 다시 적으면 계약이 늘 때
# 이 파일이 조용히 뒤처지므로 모델을 그대로 쓴다. `scripts/` 는 import-linter 의
# `root_packages` 밖이라 이 import 는 모듈 경계를 어기지 않는다.
from server.database.entities import PackEmbedding, RulePack  # noqa: E402

DEFAULT_DSN = "postgresql+psycopg://app:app@localhost:5432/app"


class LoadError(RuntimeError):
    """적재 실패."""


def dsn_from_env() -> str:
    """접속 주소. SQLAlchemy 는 `postgresql+psycopg://` 를 그대로 읽는다."""
    return os.environ.get("APP_DATABASE_URL", DEFAULT_DSN)


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
) -> tuple[RulePack, list[PackEmbedding]]:
    """팩을 `RulePack` 한 행과 `PackEmbedding` 여러 행으로 편다.

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
    head = RulePack(
        pack_version=pack["pack_version"],
        product_code=product["code"],
        product_name=product["name"],
        product_category=product["category"],
        published_at=datetime.fromisoformat(pack["published_at"]),
        published_by=pack.get("published_by"),
        embedding_model=declared["model"],
        embedding_dim=declared["dim"],
        doc=pack,
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
        PackEmbedding(
            pack_version=pack["pack_version"],
            item_code=code,
            embedding_id=embedding_id,
            source=source,
            ordinal=ordinal,
            body_text=body,
            embedding=vector,
            model=model.name,
            dim=model.dim,
        )
        for (code, embedding_id, source, ordinal, body), vector in zip(slots, vectors, strict=True)
    ]
    return head, embeddings


def load(pack: dict[str, Any], url: str, model: EmbeddingModel, replace: bool = False) -> int:
    """팩 한 벌을 넣는다. 같은 버전이 있으면 `replace` 없이는 거절한다."""
    head, embeddings = rows(pack, model)
    version = pack["pack_version"]
    with Session(create_engine(url)) as session:
        existing = session.get(RulePack, version)
        if existing is not None:
            if not replace:
                raise LoadError(f"{version} 이 이미 있음. 팩은 불변이라 새 버전을 내는 것이 원칙")
            # pack_embeddings 의 FK 가 CASCADE 라 머리만 지우면 따라 지워진다.
            session.delete(existing)
            session.flush()
        session.add(head)
        # 두 모델 사이에 relationship 이 없어 SQLAlchemy 가 삽입 순서를 모른다.
        # flush 로 머리를 먼저 넣지 않으면 자식이 FK 위반으로 튕긴다.
        session.flush()
        session.add_all(embeddings)
        session.commit()
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
