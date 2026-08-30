"""rulepack 테스트가 함께 쓰는 것.

번들 하나를 만드는 데 PDF 구조 추출이 도는데 [실측] 상품당 3.5~3.9초다. 파일마다
따로 만들면 그만큼씩 다시 문다. session 범위로 한 번만 만들어 공유한다. 픽스처를
변형하는 쪽은 `deepcopy` 를 뜨므로 공유해도 안전하다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from rulepack import paths
from rulepack.pipeline import build_product_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES = paths.config_dir(REPO_ROOT) / "candidate_rules.json"
TEST_APPROVAL_KEY = "test-approval-key-that-is-at-least-32-bytes"


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
    """원천 7종의 해시·쪽수·파서 신원. 쪽수와 원천 수의 진실 원천이다."""
    from rulepack.source_manifest import build_run_manifest

    return build_run_manifest(REPO_ROOT)
