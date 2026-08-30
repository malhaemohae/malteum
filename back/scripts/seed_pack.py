#!/usr/bin/env python3
"""규정 팩 JSON → postgres `rule_packs` 적재 (개발·시연 준비용)

M2 engine 이 팩을 DB 에서 읽으려면 먼저 팩이 DB 에 있어야 한다. 이 스크립트가 그 한 칸을
채운다. `rule_packs.doc` 이 팩 전체이고 나머지 컬럼은 조회용 사본이라, engine 쪽 PackSource
구현은 다음 한 줄로 끝난다 (db/SCHEMA.md 2절):

    SELECT doc FROM rule_packs WHERE pack_version = %s

**실제 팩 발행 파이프라인은 M3(rulepack) 소유다.** 이 스크립트는 이미 발행된 팩 JSON 을
개발용 DB 에 넣기만 하며, 추출·승인·좌표 대조에는 관여하지 않는다.

벡터는 넣지 않는다. 팩 JSON 에 임베딩 본체가 없고(`embedding_id` 만 참조로 둔다),
벡터 생성은 임베딩 모델을 쥔 쪽의 일이다. `pack_embeddings` 는 비워 둔다.

사용:
    uv run python scripts/seed_pack.py                    # pack_dir 의 rulepack_*.json 전부
    uv run python scripts/seed_pack.py DEP-2026.08-v4     # 버전 지정
    uv run python scripts/seed_pack.py ../some/pack.json  # 파일 지정
    uv run python scripts/seed_pack.py --replace ...      # 이미 있으면 지우고 다시 (개발용)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACK = HERE.parent
sys.path.insert(0, str(BACK))  # 스크립트는 back/ 이 아니라 scripts/ 에서 실행된다

from jsonschema import Draft202012Validator  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from server.bootstrap.settings import get_settings  # noqa: E402
from server.database.entities import RulePack  # noqa: E402

SCHEMA_PATH = BACK / "contracts" / "rulepack.schema.json"


def load_pack(path: Path) -> dict[str, Any]:
    """팩을 읽고 계약을 만족하는지 본다. 계약을 벗어난 팩은 DB 에 넣지 않는다."""
    pack = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(pack), key=lambda e: list(e.path))
    if errors:
        joined = "\n  ".join(f"{list(e.path)}: {e.message}" for e in errors[:5])
        raise SystemExit(f"{path.name} 이 rulepack.schema.json 을 만족하지 않는다:\n  {joined}")
    return pack


def to_row(pack: dict[str, Any]) -> RulePack:
    """조회용 컬럼은 doc 에서 복사한다. 정본은 doc 한 칸이다."""
    return RulePack(
        pack_version=pack["pack_version"],
        product_code=pack["product"]["code"],
        product_name=pack["product"]["name"],
        product_category=pack["product"]["category"],
        published_at=datetime.fromisoformat(pack["published_at"]),
        published_by=pack.get("published_by"),
        embedding_model=pack["embedding"]["model"],
        embedding_dim=pack["embedding"]["dim"],
        doc=pack,
    )


def resolve(target: str | None, pack_dir: Path) -> list[Path]:
    if target is None:
        return sorted(pack_dir.glob("rulepack_*.json"))
    path = Path(target)
    if path.suffix == ".json":
        return [path if path.is_absolute() else (Path.cwd() / path).resolve()]
    return [pack_dir / f"rulepack_{target}.json"]


def seed(paths: list[Path], url: str, replace: bool) -> int:
    engine = create_engine(url)
    seeded = 0
    with Session(engine) as session:
        for path in paths:
            if not path.exists():
                raise SystemExit(f"팩 파일이 없다: {path}")
            pack = load_pack(path)
            version = pack["pack_version"]
            existing = session.get(RulePack, version)
            if existing is not None:
                if not replace:
                    print(f"  건너뜀  {version}  (이미 있음. 팩은 불변이다. 덮으려면 --replace)")
                    continue
                session.delete(existing)  # pack_embeddings 는 CASCADE 로 함께 지워진다
                session.flush()
                print(f"  교체    {version}")
            session.add(to_row(pack))
            print(f"  적재    {version}  {pack['product']['name']}  항목 {len(pack['items'])} 개")
            seeded += 1
        session.commit()

        total = session.scalars(select(RulePack.pack_version).order_by(RulePack.pack_version)).all()
    print(f"\nrule_packs 현재: {', '.join(total) if total else '(비어 있음)'}")
    return seeded


def main(argv: list[str]) -> int:
    replace = "--replace" in argv
    rest = [a for a in argv if not a.startswith("--")]
    settings = get_settings()
    paths = resolve(rest[0] if rest else None, settings.pack_dir)
    if not paths:
        raise SystemExit(f"팩 파일을 찾지 못했다: {settings.pack_dir}/rulepack_*.json")
    print(f"DB: {settings.database_url}")
    seed(paths, settings.database_url, replace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
