"""L2 골든셋의 정합과 평가 스크립트의 경로를 본다.

골든셋은 검색 방식을 바꿀 때마다 같은 기준으로 재는 장치라, 그 자체가 낡으면
평가가 통째로 조용히 무의미해진다. 여기서 세 가지를 막는다. 골든셋이 없는 항목
코드를 기대하는 것, 금지 항목이 평가에서 빠지는 것, 평가 스크립트의 검색면이
적재(`load_pack.rows`)와 어긋나는 것.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from rulepack import paths

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN = paths.config_dir(REPO_ROOT) / "golden_utterances.json"
PACK_FIXTURE = REPO_ROOT / "back" / "contracts" / "fixtures" / "rulepack_DEP-2026.08-v4.json"


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]


def test_ids_and_utterances_are_unique(cases) -> None:
    """중복 케이스는 지표를 그 발화 쪽으로 몰래 가중한다."""
    ids = [case["id"] for case in cases]
    utterances = [case["utterance"] for case in cases]
    assert len(ids) == len(set(ids))
    assert len(utterances) == len(set(utterances))


def test_expected_codes_exist_in_candidates(cases, bundles) -> None:
    """골든셋이 기대하는 코드는 실제 후보에 있어야 한다.

    원천을 갈면 항목 코드가 바뀐다(2026-08-30 에 셋이 사라졌다). 골든셋에 옛
    코드가 남으면 그 케이스는 영원히 실패해 지표만 흐린다.
    """
    real = {item["code"] for bundle in bundles.values() for item in bundle["items"]}
    missing = sorted({code for case in cases for code in case["expected"]} - real)
    assert not missing, f"골든셋이 없는 항목 코드를 기대한다: {missing}"


def test_unrelated_cases_exist(cases) -> None:
    """무관 발화 없이는 분리력(게이트)을 잴 수 없다. 그게 2026-09-01 실측의 핵심 발견이었다."""
    unrelated = [case for case in cases if case["kind"] == "unrelated"]
    assert len(unrelated) >= 3
    assert all(case["expected"] == [] for case in unrelated)


def test_every_forbidden_item_is_covered(cases, bundles) -> None:
    """금지 항목은 컴플라이언스에 직결되는데 예시·검색 커버리지에 의존한다.

    새 forbidden 항목이 팩에 들어왔는데 골든셋에 발화가 없으면, 그 항목이 L2 에
    안 잡혀도 아무 지표가 안 움직인다. 항목 추가 시점에 여기서 막는다.
    """
    forbidden = {
        item["code"]
        for bundle in bundles.values()
        for item in bundle["items"]
        if item.get("type") == "forbidden" and "-REJ-" not in item["code"]
    }
    covered = {code for case in cases for code in case["expected"]}
    uncovered = sorted(forbidden - covered)
    assert not uncovered, f"골든셋에 발화가 없는 금지 항목: {uncovered}"


def test_surfaces_match_load_pack_rows() -> None:
    """평가 스크립트의 검색면이 적재와 같아야 결과가 운영으로 옮겨진다.

    `eval_l2_goldenset.search_surfaces` 는 `load_pack.rows` 의 열거를 옮겨 적은
    것이다. 한쪽에 검색면(예: jargon_term)이 추가되면 여기서 어긋난다.
    """
    from eval_l2_goldenset import search_surfaces
    from load_pack import rows

    from rulepack.embedding import DeterministicFakeEmbedding

    pack = json.loads(PACK_FIXTURE.read_text(encoding="utf-8"))
    model = DeterministicFakeEmbedding()
    declared = deepcopy(pack)
    declared["embedding"] = {"model": model.name, "dim": model.dim}

    _, embeddings = rows(declared, model, encode=False)
    assert search_surfaces(pack) == [
        (row.item_code, row.source, row.body_text) for row in embeddings
    ]


def test_evaluate_runs_end_to_end_with_fake_model(cases) -> None:
    """fake 모델로 평가 경로가 끝까지 도는지 본다. 품질은 안 본다(해시 벡터라 뜻이 없다)."""
    from eval_l2_goldenset import dense_ranker, engine_ranker, evaluate, make_models

    pack = json.loads(PACK_FIXTURE.read_text(encoding="utf-8"))
    passage_model, query_model = make_models("fake")
    results = evaluate(pack, cases, dense_ranker(pack, passage_model, query_model), top_k=3)
    engine_results = evaluate(pack, cases, engine_ranker(PACK_FIXTURE, query_model), top_k=3)
    assert [row["id"] for row in engine_results] == [row["id"] for row in results]

    wanted = [case for case in cases if case["product"] in ("deposit", "any")]
    assert [row["id"] for row in results] == [case["id"] for case in wanted]
    for row in results:
        assert len(row["top"]) == 3
        if row["expected"]:
            assert isinstance(row["recall_hit"], bool)
        else:
            assert row["recall_hit"] is None
