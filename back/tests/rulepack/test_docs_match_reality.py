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
from functools import cache
from pathlib import Path

import pytest

from rulepack import paths

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = sorted((REPO_ROOT / "back" / "rulepack" / "docs").glob("*.md")) + [
    REPO_ROOT / "back" / "rulepack" / "AGENTS.md"
]

# 문서가 경로를 줄여 적는다. 한 곳에서라도 찾히면 실재하는 것으로 본다.
SEARCH_ROOTS = (
    REPO_ROOT,
    REPO_ROOT / "back",
    REPO_ROOT / "back" / "rulepack",
    paths.config_dir(REPO_ROOT),
    REPO_ROOT / "back" / "rulepack" / "docs",
    REPO_ROOT / "back" / "scripts",
    paths.contracts_dir(REPO_ROOT),
    paths.docs_dir(REPO_ROOT),
)

# 2026-08-30 에 M1 의 rule_packs·pack_embeddings 로 통합하며 걷어낸 이름.
# 이력 절 밖에서 이 이름이 나오면 그 문단이 낡은 것이다.
REMOVED_TABLES = ("pack", "pack_item", "item_embedding")

# 원천 감사 기록. 이 문서의 판정 표가 사라지면 쪽수 대조가 조용히 없어지므로
# 최소 한 줄을 요구한다. 이름을 바꾸면 아래 단언이 그 자리에서 깨진다.
SOURCE_AUDIT_DOC = REPO_ROOT / "back" / "rulepack" / "docs" / "SOURCES.md"

_HISTORY_HEADING = re.compile(r"최근 변경|해결됨|교체 기록")
_FILE_REF = re.compile(r"`([\w/.가-힣-]+\.(?:py|json|md|sql|yml|toml))`")
_BACKTICK = re.compile(r"`([^`\n]+)`")


@cache
def _prose(doc: Path) -> str:
    """이력 절을 걷어낸 현재 서술. 문서마다 한 번만 읽고 훑는다."""
    return _current_prose(doc.read_text(encoding="utf-8"))


def _current_prose(text: str) -> str:
    """이력을 적는 절을 걷어낸 나머지. 지금 상태를 설명하는 부분만 남는다."""
    kept: list[str] = []
    skip_at_level: int | None = None
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        # 셸 주석(`# 후보 생성`)을 제목으로 읽으면 건너뛰기 상태가 뒤집힌다.
        heading = None if in_fence else re.match(r"^(#+)\s+(.*)$", line)
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
            for ref in _FILE_REF.findall(_prose(doc))
            if not any((root / ref).exists() for root in SEARCH_ROOTS)
        }
    )
    assert not missing, f"{doc.name} 이 없는 파일을 가리킨다: {missing}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_docs_do_not_name_removed_tables(doc: Path) -> None:
    """걷어낸 테이블 이름을 현재 서술이 가리키면 안 된다.

    `pack_version` 처럼 살아 있는 이름과 겹치지 않도록 백틱 안이 정확히 그
    이름이거나 `이름.열` 일 때만 잡는다. 열까지 붙은 표기를 안 보다가
    `item_embedding.vector` 가 검사를 빠져나간 적이 있다 (2026-08-31).
    """
    named = sorted(
        {
            token
            for token in _BACKTICK.findall(_prose(doc))
            if token.strip().split(".")[0] in REMOVED_TABLES
        }
    )
    assert not named, (
        f"{doc.name} 이 걷어낸 테이블을 현재 서술에서 가리킨다: {named}. "
        "이력이면 '최근 변경'·'해결됨'·'교체 기록' 절로 옮기고, 아니면 "
        "rule_packs·pack_embeddings 로 고친다"
    )


def test_removed_tables_really_are_gone() -> None:
    """위 목록이 낡지 않았는지 본다. 되살아난 이름을 계속 막고 있으면 거짓 실패가 난다."""
    alive = sorted(set(REMOVED_TABLES) & set(_real_tables()))
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
    cited = set(_ITEM_CODE.findall(_prose(doc)))
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
    text = _prose(doc)
    stated = {int(value) for value in _DIMENSION.findall(text)}
    wrong = sorted(stated - {model.dim})
    assert not wrong, f"{doc.name} 이 {wrong}차원이라 적었지만 구현은 {model.dim}차원"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_documented_commands_actually_parse(doc: Path) -> None:
    """문서에 적은 명령줄이 실제 인자 정의로 파싱돼야 한다.

    사용법은 손으로 적는 자리라 옵션 이름이 바뀌어도 아무도 모른다. 실제 파서에
    넣어 보면 없는 옵션과 빠진 인자가 그 자리에서 드러난다.
    """
    from load_pack import build_parser as load_pack_parser

    from rulepack.cli import build_parser as cli_parser

    text = doc.read_text(encoding="utf-8")
    blocks = _BASH_BLOCK.findall(text)
    checked = 0
    for block in blocks:
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
    runnable = [b for b in blocks if "rulepack.cli" in b or "load_pack.py" in b]
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
    text = _prose(doc)
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
    text = _prose(doc)
    gone = sorted(
        {
            table
            for block in _SQL_BLOCK.findall(text)
            for table in _SQL_TABLE.findall(block)
            if table not in tables
        }
    )
    assert not gone, f"{doc.name} 의 SQL 이 없는 테이블을 건드린다: {gone}"


_PAGES = re.compile(r"(\d+)\s*쪽")
_KINDS = re.compile(r"(\d+)\s*종")
# 원천을 세는 문맥에서만 'N종' 을 검사한다. "계약 fixture 4종" 은 원천 수가 아니다.
_SOURCE_CONTEXT = re.compile(r"규정\s*(?:PDF|문서)|\.pdf")
# 쪽수를 세는 줄인지. 근거 인용의 페이지 번호("근거 3쪽")와 구분한다.
_SOURCE_LINE = re.compile(r"설명서|약관|원천|PDF|pdf|가이드라인|대책|보호법")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_docs_state_real_page_counts(doc: Path, run_manifest) -> None:
    """문서가 말하는 쪽수가 실제 원천 PDF 와 같아야 한다.

    원천을 갈면 쪽수가 바뀐다. 2026-08-29 에 26쪽이 24쪽이 됐고 2026-08-30 에
    7쪽이 4쪽이 됐다. 문서에 옛 쪽수가 남으면 팀원이 다른 파일을 받은 줄 안다.
    옛 쪽수를 적는 자리는 이력 절이고 거기는 검사에서 뺀다.
    """
    real = {source.page_count for source in run_manifest.sources}
    stated = {
        int(value)
        for line in _prose(doc).splitlines()
        if _SOURCE_LINE.search(line)
        for value in _PAGES.findall(line)
    }
    wrong = sorted(stated - real)
    assert not wrong, (
        f"{doc.name} 이 {wrong}쪽이라 적었지만 실제 원천 쪽수는 {sorted(real)} 뿐이다. "
        "원천을 갈았으면 새 쪽수로 고치고, 옛 쪽수 이야기면 이력 절로 옮긴다"
    )


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_docs_state_real_source_count(doc: Path, run_manifest) -> None:
    """문서가 말하는 규정 원천 개수가 MANIFEST 와 같아야 한다."""
    real = len(run_manifest.sources)
    wrong = sorted(
        {
            int(value)
            for line in _prose(doc).splitlines()
            if _SOURCE_CONTEXT.search(line)
            for value in _KINDS.findall(line)
            if int(value) != real
        }
    )
    assert not wrong, f"{doc.name} 이 원천을 {wrong}종이라 적었지만 실제는 {real}종"


_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$", re.MULTILINE)


def _matching_source(label: str, sources) -> list:
    """표 첫 칸의 이름과 맞는 원천을 찾는다.

    문서는 파일명과 다른 순서로 부른다(`정기예금 상품설명서` ↔
    `05_상품설명서_정기예금`). 이름을 조각으로 쪼개 전부 들어있는지 본다.
    """
    parts = [part for part in re.split(r"[\s·()]+", label.strip()) if part]
    if not parts:
        return []
    return [s for s in sources if all(part in s.doc_id.replace("_", "") for part in parts)]


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_doc_tables_state_the_right_page_count(doc: Path, run_manifest) -> None:
    """표에서 쪽수를 적은 줄은 그 문서의 실제 쪽수와 같아야 한다.

    산문에서는 어느 문서 이야기인지 알기 어려워 "없는 쪽수인가" 까지만 본다.
    그래서 정기예금(4쪽)을 24쪽이라 적어도 가계대출이 24쪽이라 통과했다. 표는
    한 줄에 이름과 쪽수가 함께 있어 그 연결이 확실하다.
    """
    text = _prose(doc)
    checked = 0
    for row in _TABLE_ROW.findall(text):
        cells = [cell.strip() for cell in row.split("|")]
        if len(cells) < 2 or set(cells[0]) <= {"-", " "}:
            continue  # 헤더 구분선
        pages = {int(value) for value in _PAGES.findall(row)}
        if not pages or not _SOURCE_LINE.search(row):
            continue  # 쪽수가 없거나 원천 이야기가 아닌 줄은 연결할 필요가 없다
        found = _matching_source(cells[0], run_manifest.sources)
        assert len(found) == 1, (
            f"{doc.name} 의 표에서 `{cells[0]}` 이 어느 원천인지 정하지 못했다"
            f"(맞은 개수 {len(found)}). 표기를 파일명과 맞추거나 이 검사를 고쳐야 한다"
        )
        assert pages == {found[0].page_count}, (
            f"{doc.name} 의 표: `{cells[0]}` 을 {sorted(pages)}쪽이라 적었지만 "
            f"실제 {found[0].doc_id} 는 {found[0].page_count}쪽"
        )
        checked += 1

    # 표를 통째로 지우면 검사가 조용히 사라진다. SOURCES 는 원천 감사 기록이라
    # 원천별 판정 표가 반드시 있어야 하므로, 거기서는 최소 한 줄을 요구한다.
    # (`쪽` 은 "어느 쪽" 처럼 일반 명사로도 쓰여 글자만 보고 판단하면 안 된다.)
    if doc == SOURCE_AUDIT_DOC:
        assert checked, f"{doc.name} 의 원천별 판정 표에서 쪽수를 한 줄도 대조하지 못했다"
