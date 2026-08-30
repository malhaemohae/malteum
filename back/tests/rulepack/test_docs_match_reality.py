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
