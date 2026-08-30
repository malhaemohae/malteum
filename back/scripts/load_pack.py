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
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

BACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACK))


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
from server.bootstrap.settings import get_settings  # noqa: E402
from server.database.entities import (  # noqa: E402
    EMBEDDING_SOURCES,
    PackEmbedding,
    RulePack,
)
from server.database.session import make_sessions  # noqa: E402


class LoadError(RuntimeError):
    """적재 실패."""


class PackAlreadyLoaded(LoadError):
    """같은 버전이 이미 있음. 여러 팩을 넣을 때는 이것만 건너뛰고 계속한다."""


def dsn_from_env() -> str:
    """접속 주소. `back/.env` 까지 읽는 server 설정을 그대로 쓴다.

    환경변수만 직접 읽으면 `.env` 에 적어 둔 값을 못 봐서, 같은 실행 안에서
    `pack_dir` 은 설정을 따르고 DB 만 다른 곳을 가리키게 된다.
    """
    return get_settings().database_url


@lru_cache(maxsize=4)
def _model(name: str, dim: int) -> EmbeddingModel:
    """이름·차원마다 구현 하나. 팩마다 새로 만들면 0.5GB 모델을 다시 읽는다."""
    for candidate in (E5SmallEmbedding(), DeterministicFakeEmbedding(dim=dim)):
        if candidate.name == name:
            return candidate
    raise LoadError(f"모르는 임베딩 모델: {name}. 구현을 먼저 붙여야 함")


def model_for(pack: dict[str, Any]) -> EmbeddingModel:
    """팩이 적은 모델로 구현을 고른다. 아무 구현으로나 만들면 팩과 다른 값이 나온다."""
    declared = pack["embedding"]
    return _model(declared["model"], declared["dim"])


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


def check_contract(pack: dict[str, Any]) -> None:
    """팩이 `rulepack.schema.json` 을 만족하는지 본다.

    `compile` 이 이미 검사하지만 그건 발행 시점 이야기다. 손으로 만든 팩이나 옛
    버전을 넣을 때는 그 믿음이 성립하지 않으므로 넣기 직전에 다시 본다. 검증은
    컴파일러 것을 그대로 쓴다. 따로 적으면 한쪽만 느슨해진다. 실제로 사본은
    `format_checker` 를 안 넘겨 `date-time` 형식을 못 잡고 있었다.
    """
    from rulepack import paths
    from rulepack.compiler import _validate_pack_schema

    try:
        _validate_pack_schema(paths.find_repo_root(), pack)
    except CompileError as exc:
        raise LoadError(f"팩이 rulepack.schema.json 을 만족하지 않음: {exc}") from exc


def resolve(target: str | None, pack_dir: Path) -> list[Path]:
    """인자를 적재 대상 파일 목록으로 바꾼다.

    없으면 `pack_dir` 의 발행물 전부, 버전만 주면 그 이름의 파일, 경로면 그대로.
    """
    if target is None:
        return sorted(pack_dir.glob("rulepack_*.json"))
    path = Path(target)
    if path.suffix == ".json":
        return [path if path.is_absolute() else (Path.cwd() / path).resolve()]
    return [pack_dir / f"rulepack_{target}.json"]


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

    embeddings: list[PackEmbedding] = []
    for item in pack["items"]:
        bodies = (
            ("item", [embedding_text(item)]),
            ("forbidden_example", item.get("forbidden_examples") or []),
            ("risk_example", item.get("risk_examples") or []),
            ("plain_language", item.get("plain_language") or []),
        )
        for source, values in bodies:
            if source not in EMBEDDING_SOURCES:  # 모델이 허용하는 출처만
                raise LoadError(f"모르는 임베딩 출처: {source}")
            for ordinal, body in enumerate(values):
                embeddings.append(
                    PackEmbedding(
                        pack_version=pack["pack_version"],
                        item_code=item["code"],
                        embedding_id=item.get("embedding_id"),
                        source=source,
                        ordinal=ordinal,
                        body_text=str(body),
                        model=model.name,
                        dim=model.dim,
                    )
                )

    # dry-run 은 행 수만 세므로 모델(약 0.5GB)을 올리지 않는다. 그때 벡터 자리는
    # None 이라 그 결과를 DB 에 넣으면 안 된다.
    if encode and embeddings:
        vectors = model.encode([row.body_text for row in embeddings])
        for row, vector in zip(embeddings, vectors, strict=True):
            row.embedding = vector

    return head, embeddings


@lru_cache(maxsize=4)
def _sessions(url: str):
    """접속 주소마다 세션 팩토리 하나. 팩마다 만들면 커넥션 풀이 매번 새로 생긴다.

    직접 `create_engine` 을 부르면 `make_sessions` 가 주는 `pool_pre_ping`(끊긴
    연결을 조용히 되살림)을 놓친다.
    """
    return make_sessions(url)


def load(pack: dict[str, Any], url: str, model: EmbeddingModel, replace: bool = False) -> int:
    """팩 한 벌을 넣는다. 같은 버전이 있으면 `replace` 없이는 거절한다."""
    head, embeddings = rows(pack, model)
    version = pack["pack_version"]
    with _sessions(url)() as session:
        existing = session.get(RulePack, version)
        if existing is not None:
            if not replace:
                raise PackAlreadyLoaded(
                    f"{version} 이 이미 있음. 팩은 불변이라 새 버전을 내는 것이 원칙"
                )
            # delete-orphan 과 DB 의 ON DELETE CASCADE 가 임베딩까지 함께 지운다.
            session.delete(existing)
            session.flush()
        # 관계로 묶어 두면 SQLAlchemy 가 머리를 먼저 넣는다.
        head.embeddings = embeddings
        session.add(head)
        session.commit()
    return len(embeddings)


def build_parser() -> argparse.ArgumentParser:
    """인자 정의. 문서가 적은 사용법이 실제로 파싱되는지 테스트가 이걸로 확인한다."""
    parser = argparse.ArgumentParser(description="팩 JSON 을 postgres 에 적재")
    parser.add_argument(
        "pack",
        nargs="?",
        help="compile 산출물 · 팩 파일 경로 · 팩 버전. 없으면 pack_dir 의 rulepack_*.json 전부",
    )
    parser.add_argument(
        "--replace", action="store_true", help="같은 버전이 있으면 지우고 다시 넣음"
    )
    parser.add_argument("--dry-run", action="store_true", help="행만 만들어 보고 DB 는 안 건드림")
    parser.add_argument(
        "--unsigned",
        action="store_true",
        help="서명 없는 팩 본문을 받아들임. 무결성 검증을 건너뛰므로 개발용",
    )
    return parser


def _apply(path: Path, args: argparse.Namespace, *, skip_existing: bool) -> dict[str, Any]:
    """팩 하나를 처리하고 결과를 낸다. 세 갈래가 같은 모양으로 끝난다."""
    if not path.exists():
        raise LoadError(f"팩 파일이 없음: {path}")
    pack = unwrap(json.loads(path.read_text(encoding="utf-8")), allow_unsigned=args.unsigned)
    check_contract(pack)
    model = model_for(pack)
    base = {"pack_version": pack["pack_version"], "items": len(pack["items"])}

    if args.dry_run:
        _, embeddings = rows(pack, model, encode=False)
        return base | {"embeddings": len(embeddings), "dry_run": True}
    try:
        loaded = load(pack, dsn_from_env(), model, replace=args.replace)
    except PackAlreadyLoaded as exc:
        # 여러 팩을 한 번에 넣을 때 하나가 이미 있다고 나머지까지 멈추면,
        # 다시 돌려도 첫 팩에서 또 막혀 아무것도 진행되지 않는다.
        if not skip_existing:
            raise
        return base | {"skipped": str(exc)}
    return base | {"embeddings": loaded, "loaded": True}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pack_dir = Path(get_settings().pack_dir)
    targets = resolve(args.pack, pack_dir)
    if not targets:
        raise LoadError(f"적재할 팩을 찾지 못함: {pack_dir}/rulepack_*.json")

    # 대상을 고르는 방법이 늘어도 이 한 줄만 보면 된다.
    skip_existing = args.pack is None
    for path in targets:
        result = _apply(path, args, skip_existing=skip_existing)
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
