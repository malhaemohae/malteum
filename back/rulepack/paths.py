"""저장소 배치 해석. 경로 가정을 이 파일 한 곳에만 둔다.

같은 코드가 두 배치에서 돈다.

  개인 작업장:  <root>/contracts · <root>/rulepack/config · <root>/03_규정문서
  팀 레포:      <root>/back/contracts · <root>/back/rulepack/config · <root>/assets/03_규정문서

호출부가 배치를 알면 이식 때마다 전 파일을 고치게 된다. 실제로 8곳에 흩어져
있던 것을 모았다 (2026-08-27).
"""

from __future__ import annotations

from pathlib import Path


class LayoutError(FileNotFoundError):
    """어느 배치로도 경로를 찾지 못함."""


def _first(root: Path, *candidates: str) -> Path:
    for cand in candidates:
        p = root / Path(cand)
        if p.exists():
            return p
    raise LayoutError(f"{candidates} 중 어느 것도 {root} 아래에 없음")


LAYOUTS: tuple[tuple[str, str], ...] = (
    ("back/contracts", "assets/03_규정문서"),
    ("contracts", "03_규정문서"),
)


def find_repo_root(start: Path | None = None) -> Path:
    """자기 위치에서 위로 올라가며 계약과 규정 원천이 함께 보이는 첫 폴더를 루트로 삼는다.

    parents[N] 하드코딩은 배치(개인 작업장 src 레이아웃 vs 팀 레포 flat)마다
    N 이 달라져 실제로 깨졌다 (2026-08-27).

    계약 폴더만 보면 팀 레포에서 back/ 이 먼저 걸린다. back/contracts 가 있어
    back/ 을 루트로 반환하고, 그러면 규정 원천을 back/assets 에서 찾다 실패한다.
    배치마다 계약과 원천을 쌍으로 확인해야 한 단계 위가 루트로 잡힌다 (2026-08-29).
    """
    cur = (start or Path(__file__)).resolve()
    for cand in [cur, *cur.parents]:
        if any((cand / c).is_dir() and (cand / d).is_dir() for c, d in LAYOUTS):
            return cand
    raise LayoutError(f"{cur} 위쪽에서 계약 폴더와 규정 원천 폴더의 쌍을 찾지 못함")


def contracts_dir(root: Path) -> Path:
    return _first(root, "back/contracts", "contracts")


def docs_dir(root: Path) -> Path:
    """규정 PDF 원천 폴더."""
    return _first(root, "assets/03_규정문서", "03_규정문서")


def config_dir(root: Path) -> Path:
    return _first(root, "back/rulepack/config", "rulepack/config")


def default_artifacts_dir(root: Path) -> Path:
    base = _first(root, "back/rulepack", "rulepack")
    return base / "artifacts"


def default_work_dir(root: Path) -> Path:
    base = _first(root, "back/rulepack", "rulepack")
    return base / "work"
