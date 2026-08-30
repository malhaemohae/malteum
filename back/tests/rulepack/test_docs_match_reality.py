"""rulepack 문서가 실물과 어긋나지 않는지 본다.

숫자와 목록은 `test_status_doc_matches_actual_counts` 가 이미 기계로 대조한다.
그래서 이 세션 내내 표는 한 번도 안 틀렸다. 반면 **손으로 적은 서술**은 아무도
안 지켜서, 저장 스키마를 M1 쪽으로 통합한 뒤 데이터 흐름 그림이 사라진 테이블을
계속 가리키고 있었다 (2026-08-30). 사람이 훑어야만 잡히던 부류를 여기서 막는다.

이력을 적는 절은 검사에서 뺀다. "옛 테이블을 걷어냈다" 는 서술은 지워진 이름을
가리키는 것이 맞기 때문이다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = sorted((REPO_ROOT / "back" / "rulepack" / "docs").glob("*.md")) + [
    REPO_ROOT / "back" / "rulepack" / "AGENTS.md"
]

# 문서가 경로를 줄여 적는다. 한 곳에서라도 찾히면 실재하는 것으로 본다.
SEARCH_ROOTS = (
    REPO_ROOT,
    REPO_ROOT / "back",
    REPO_ROOT / "back" / "rulepack",
    REPO_ROOT / "back" / "rulepack" / "config",
    REPO_ROOT / "back" / "rulepack" / "docs",
    REPO_ROOT / "back" / "scripts",
    REPO_ROOT / "back" / "contracts",
    REPO_ROOT / "assets" / "03_규정문서",
)

# 2026-08-30 에 M1 의 rule_packs·pack_embeddings 로 통합하며 걷어낸 이름.
# 이력 절 밖에서 이 이름이 나오면 그 문단이 낡은 것이다.
REMOVED_TABLES = ("pack", "pack_item", "item_embedding")

_HISTORY_HEADING = re.compile(r"최근 변경|해결됨|교체 기록")
_FILE_REF = re.compile(r"`([\w/.가-힣-]+\.(?:py|json|md|sql|yml|toml))`")
_BACKTICK = re.compile(r"`([^`\n]+)`")


def _current_prose(text: str) -> str:
    """이력을 적는 절을 걷어낸 나머지. 지금 상태를 설명하는 부분만 남는다."""
    kept: list[str] = []
    skip_at_level: int | None = None
    for line in text.splitlines():
        heading = re.match(r"^(#+)\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            if skip_at_level is not None and level <= skip_at_level:
                skip_at_level = None
            if skip_at_level is None and _HISTORY_HEADING.search(heading.group(2)):
                skip_at_level = level
        if skip_at_level is None:
            kept.append(line)
    return "\n".join(kept)


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_docs_reference_files_that_exist(doc: Path) -> None:
    """문서가 백틱으로 가리키는 파일이 실재해야 한다."""
    missing = sorted(
        {
            ref
            for ref in _FILE_REF.findall(_current_prose(doc.read_text(encoding="utf-8")))
            if not any((root / ref).exists() for root in SEARCH_ROOTS)
        }
    )
    assert not missing, f"{doc.name} 이 없는 파일을 가리킨다: {missing}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_docs_do_not_name_removed_tables(doc: Path) -> None:
    """걷어낸 테이블 이름을 현재 서술이 가리키면 안 된다.

    `pack_version` 처럼 살아 있는 이름과 겹치지 않도록 백틱 안이 정확히 그
    이름일 때만 잡는다.
    """
    named = sorted(
        {
            token
            for token in _BACKTICK.findall(_current_prose(doc.read_text(encoding="utf-8")))
            if token.strip() in REMOVED_TABLES
        }
    )
    assert not named, (
        f"{doc.name} 이 걷어낸 테이블을 현재 서술에서 가리킨다: {named}. "
        "이력이면 '최근 변경'·'해결됨'·'교체 기록' 절로 옮기고, 아니면 "
        "rule_packs·pack_embeddings 로 고친다"
    )


def test_removed_tables_really_are_gone() -> None:
    """위 목록이 낡지 않았는지 본다. 되살아난 이름을 계속 막고 있으면 거짓 실패가 난다."""
    import server.database.entities  # noqa: F401
    from server.database.base import Base

    alive = sorted(set(REMOVED_TABLES) & set(Base.metadata.tables))
    assert not alive, f"{alive} 은 실제로 존재하는 테이블이다. REMOVED_TABLES 에서 빼야 한다"


_ITEM_CODE = re.compile(r"\b(?:DEP|LOAN)-[A-Z]{3}-\d{3}\b")
_BASH_BLOCK = re.compile(r"```bash\n(.*?)```", re.DOTALL)
_PLACEHOLDER = re.compile(r"<[^>]+>")
_DIMENSION = re.compile(r"(\d+)\s*차원")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_docs_cite_item_codes_that_exist(doc: Path, bundles) -> None:
    """문서가 언급한 항목 코드가 실제 후보에 있어야 한다.

    원천을 갈면 항목 코드가 바뀐다. 2026-08-30 에 `DEP-INT-004` · `DEP-BAN-002` ·
    `DEP-LON-001` 셋이 사라졌는데, 그때 문서 현재 서술에 남아 있었다면 아무도
    못 잡았다.
    """
    real = {item["code"] for bundle in bundles.values() for item in bundle["items"]}
    cited = set(_ITEM_CODE.findall(_current_prose(doc.read_text(encoding="utf-8"))))
    gone = sorted(cited - real)
    assert not gone, (
        f"{doc.name} 이 없는 항목 코드를 가리킨다: {gone}. "
        "원천 교체로 코드가 바뀌었으면 현재 코드로 고치고, 이력이면 이력 절로 옮긴다"
    )


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_docs_state_real_embedding_dimension(doc: Path) -> None:
    """문서가 적은 임베딩 차원이 구현과 같아야 한다.

    차원은 팩에 묶이는 값이라 틀리면 적재가 막힌다. 문서만 보고 다른 모델을 붙이면
    실행해 봐야만 그 사실을 알게 된다.
    """
    from rulepack.embedding import E5SmallEmbedding

    model = E5SmallEmbedding()
    text = _current_prose(doc.read_text(encoding="utf-8"))
    stated = {int(value) for value in _DIMENSION.findall(text)}
    wrong = sorted(stated - {model.dim})
    assert not wrong, f"{doc.name} 이 {wrong}차원이라 적었지만 구현은 {model.dim}차원"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_documented_commands_actually_parse(doc: Path) -> None:
    """문서에 적은 명령줄이 실제 인자 정의로 파싱돼야 한다.

    사용법은 손으로 적는 자리라 옵션 이름이 바뀌어도 아무도 모른다. 실제 파서에
    넣어 보면 없는 옵션과 빠진 인자가 그 자리에서 드러난다.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "back" / "scripts"))
    from load_pack import build_parser as load_pack_parser

    from rulepack.cli import build_parser as cli_parser

    text = doc.read_text(encoding="utf-8")
    checked = 0
    for block in _BASH_BLOCK.findall(text):
        for raw in block.splitlines():
            line = _PLACEHOLDER.sub("PLACEHOLDER.json", raw.split("#", 1)[0])
            line = line.replace("[", "").replace("]", "").strip()
            if not line or line.startswith("cd "):
                continue
            if "rulepack.cli" in line:
                parser, argv = cli_parser(), line.split("rulepack.cli", 1)[1].split()
            elif "load_pack.py" in line:
                parser, argv = load_pack_parser(), line.split("load_pack.py", 1)[1].split()
            else:
                continue
            try:
                parser.parse_args(argv)
            except SystemExit as exc:  # argparse 는 인자가 틀리면 SystemExit 을 낸다
                raise AssertionError(
                    f"{doc.name} 의 명령이 파싱되지 않는다: {raw.strip()}"
                ) from exc
            checked += 1
    # 산문에서 스크립트를 언급만 하는 문서도 있다. 실행 블록이 있을 때만 요구한다.
    runnable = [b for b in _BASH_BLOCK.findall(text) if "rulepack.cli" in b or "load_pack.py" in b]
    assert checked or not runnable, f"{doc.name} 의 실행 블록을 하나도 검사하지 못했다"


_QUALIFIED = re.compile(r"`(\w+)\.(\w+)`")
_SQL_BLOCK = re.compile(r"```sql\n(.*?)```", re.DOTALL)
_SQL_TABLE = re.compile(r"\b(?:from|into|update|join)\s+(\w+)", re.IGNORECASE)


def _real_tables() -> dict[str, set[str]]:
    import server.database.entities  # noqa: F401
    from server.database.base import Base

    return {name: set(t.columns.keys()) for name, t in Base.metadata.tables.items()}


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_docs_reference_real_table_columns(doc: Path) -> None:
    """문서가 `테이블.열` 로 가리킨 열이 실제로 있어야 한다.

    테이블 이름만 맞고 그 안의 설명이 낡는 경우가 있다. `rule_packs.doc` 한 칸이
    정본이라는 서술이 그런 자리다. 저장 구조를 바꾸면 이 표기가 먼저 낡는다.
    """
    tables = _real_tables()
    text = _current_prose(doc.read_text(encoding="utf-8"))
    wrong = sorted(
        f"{table}.{column}"
        for table, column in _QUALIFIED.findall(text)
        if table in tables and column not in tables[table]
    )
    assert not wrong, f"{doc.name} 이 없는 열을 가리킨다: {wrong}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_documented_sql_targets_real_tables(doc: Path) -> None:
    """문서의 SQL 예시가 실재하는 테이블만 건드려야 한다.

    복사해 쓰라고 적어 둔 SQL 이라 낡으면 그대로 실행돼 실패한다.
    """
    tables = _real_tables()
    text = doc.read_text(encoding="utf-8")
    gone = sorted(
        {
            table
            for block in _SQL_BLOCK.findall(text)
            for table in _SQL_TABLE.findall(block)
            if table not in tables
        }
    )
    assert not gone, f"{doc.name} 의 SQL 이 없는 테이블을 건드린다: {gone}"
