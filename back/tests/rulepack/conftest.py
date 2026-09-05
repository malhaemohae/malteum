"""rulepack 테스트가 함께 쓰는 것.

번들 하나를 만드는 데 PDF 구조 추출이 도는데 [실측] 상품당 3.5~3.9초다. 파일마다
따로 만들면 그만큼씩 다시 문다. session 범위로 한 번만 만들어 공유한다. 픽스처를
변형하는 쪽은 `deepcopy` 를 뜨므로 공유해도 안전하다.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from rulepack import paths
from rulepack.pipeline import build_product_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES = paths.config_dir(REPO_ROOT) / "candidate_rules.json"

# `scripts/` 는 패키지가 아니라 import 하려면 경로를 넣어야 한다. 테스트 함수마다
# 넣으면 같은 경로가 sys.path 앞에 여러 번 쌓이고, 그 뒤 모든 import 해석이
# `back/scripts/` 를 먼저 뒤진다(거기 smoke.py · gen_models.py 가 있다).
_SCRIPTS = str(REPO_ROOT / "back" / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


@pytest.fixture(scope="session")
def bundles() -> dict[str, dict]:
    """예금·대출 번들. 후보 상태와 항목 코드의 진실 원천이다."""
    with tempfile.TemporaryDirectory() as work:
        return {
            product: build_product_bundle(REPO_ROOT, product, RULES, Path(work) / product)
            for product in ("deposit", "loan")
        }


@pytest.fixture(scope="session")
def run_manifest():
    """원천 전체의 해시·쪽수·파서 신원. 쪽수와 원천 수의 진실 원천이다."""
    from rulepack.source_manifest import build_run_manifest

    return build_run_manifest(REPO_ROOT)
