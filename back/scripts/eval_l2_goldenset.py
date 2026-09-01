#!/usr/bin/env python3
"""골든셋으로 L2 의미 검색을 잰다.

왜 있나
    2026-09-01 엔진 팀이 실물 e5-small 로 L2 를 재 봤더니 짧은 구어 발화와 항목
    설명의 유사도가 0.77~0.87 좁은 띠에 몰려 무관 발화가 분리되지 않았다. 그
    실험이 일회성 스크립트로 끝나면 검색 방식(모델 교체·자모 BM25·융합)을 바꿀
    때마다 같은 실험을 처음부터 다시 짠다. 발화와 기대 항목을
    `config/golden_utterances.json` 에 박아 두고 여기서 늘 같은 기준으로 잰다.

무엇을 재나
    발화마다 항목 순위를 매겨 top-1 정답률 · recall@k(기대 항목이 상위 k 후보에
    드는 비율) · 관련/무관 점수 분리를 보고한다. L2 는 프리필터라 최종 판정권이
    L3 에 있으므로 top-1 보다 recall@k 와 분리력이 판단 기준이다.

검색면
    `load_pack.rows` 와 같은 열거(항목 본문 + 금지·위험 예시 + 쉬운 말)를 쓴다.
    운영 L2 가 보는 `pack_embeddings` 와 같은 면을 봐야 결과가 옮겨진다. 두 열거가
    어긋나면 `tests/rulepack/test_golden_utterances.py` 가 잡는다.

    팩이 기록한 `embedding.model` 은 확인하지 않는다. 적재(`load_pack.py`)는 팩을
    만든 모델 그대로여야 하지만, 평가는 다른 모델을 갈아끼워 보는 자리다.

사용
    python scripts/eval_l2_goldenset.py                       # artifacts 의 팩 전부, e5
    python scripts/eval_l2_goldenset.py <팩.json> --model fake --top-k 3

    e5 는 첫 실행에서 모델(약 0.5GB)을 내려받는다. fake 는 결정적 해시 벡터라
    품질을 재지 못하고, 경로가 끝까지 도는지만 본다(CI 스모크용).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACK))

from rulepack.embedding import (  # noqa: E402
    DeterministicFakeEmbedding,
    E5SmallEmbedding,
    EmbeddingModel,
    embedding_text,
)

GOLDEN_DEFAULT = BACK / "rulepack" / "config" / "golden_utterances.json"
PACKS_DEFAULT_DIR = BACK / "rulepack" / "artifacts"


def search_surfaces(pack: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(item_code, source, 본문) 열거. `load_pack.rows` 와 같은 검색면이다.

    저쪽을 그대로 부르지 않는 이유는 ORM 행 생성과 모델 일치 검사가 딸려 오기
    때문이다. 대신 두 열거가 같은지 테스트가 대조한다.
    """
    surfaces: list[tuple[str, str, str]] = []
    for item in pack["items"]:
        bodies = (
            ("item", [embedding_text(item)]),
            ("forbidden_example", item.get("forbidden_examples") or []),
            ("risk_example", item.get("risk_examples") or []),
            ("plain_language", item.get("plain_language") or []),
        )
        for source, values in bodies:
            for body in values:
                surfaces.append((item["code"], source, str(body)))
    return surfaces


def make_models(name: str) -> tuple[EmbeddingModel, EmbeddingModel]:
    """(팩 항목용, 발화용) 쌍. e5 는 passage/query 접두어가 달라 인스턴스가 둘이다."""
    if name == "fake":
        model = DeterministicFakeEmbedding()
        return model, model
    return E5SmallEmbedding(prefix="passage"), E5SmallEmbedding(prefix="query")


def evaluate(
    pack: dict[str, Any],
    cases: list[dict[str, Any]],
    passage_model: EmbeddingModel,
    query_model: EmbeddingModel,
    top_k: int,
) -> list[dict[str, Any]]:
    """팩 하나에 대해 케이스별 순위를 계산한다. 반환 항목은 보고와 테스트가 쓴다."""
    surfaces = search_surfaces(pack)
    passage_vectors = passage_model.encode([text for _, _, text in surfaces])
    category = pack["product"]["category"]
    chosen = [case for case in cases if case["product"] in (category, "any")]
    query_vectors = query_model.encode([case["utterance"] for case in chosen])

    results: list[dict[str, Any]] = []
    for case, query in zip(chosen, query_vectors, strict=True):
        best: dict[str, float] = {}
        for (code, _, _), vector in zip(surfaces, passage_vectors, strict=True):
            score = sum(q * v for q, v in zip(query, vector, strict=True))
            if score > best.get(code, float("-inf")):
                best[code] = score
        ranked = sorted(best.items(), key=lambda pair: pair[1], reverse=True)
        rank_of = {code: index + 1 for index, (code, _) in enumerate(ranked)}
        expected = case["expected"]
        results.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "utterance": case["utterance"],
                "expected": expected,
                "top": ranked[:top_k],
                "top1_score": ranked[0][1],
                "expected_ranks": {code: rank_of.get(code) for code in expected},
                "top1_hit": bool(expected) and ranked[0][0] in expected,
                "recall_hit": all(rank_of.get(code, 10**9) <= top_k for code in expected)
                if expected
                else None,
            }
        )
    return results


def report(pack_version: str, results: list[dict[str, Any]], top_k: int) -> None:
    print(f"\n== {pack_version} ==")
    for row in results:
        top = " ".join(f"{code}:{score:.3f}" for code, score in row["top"])
        if row["expected"]:
            ranks = ", ".join(f"{code}→{rank}위" for code, rank in row["expected_ranks"].items())
            verdict = "통과" if row["recall_hit"] else "실패"
            print(f"[{verdict}] {row['id']}  기대({ranks})  top{top_k}: {top}")
        else:
            print(f"[무관] {row['id']}  최고점 {row['top1_score']:.3f}  top{top_k}: {top}")

    scored = [row for row in results if row["expected"]]
    unrelated = [row for row in results if not row["expected"]]
    if scored:
        top1 = sum(row["top1_hit"] for row in scored)
        recall = sum(row["recall_hit"] for row in scored)
        print(f"top-1 {top1}/{len(scored)}  ·  recall@{top_k} {recall}/{len(scored)}")
    if scored and unrelated:
        related_band = [row["top1_score"] for row in scored]
        unrelated_band = [row["top1_score"] for row in unrelated]
        print(
            f"점수 분리  관련 {min(related_band):.3f}~{max(related_band):.3f}"
            f"  vs  무관 {min(unrelated_band):.3f}~{max(unrelated_band):.3f}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="골든셋으로 L2 검색을 잰다")
    parser.add_argument(
        "packs",
        nargs="*",
        type=Path,
        help=f"발행된 팩 JSON. 비우면 {PACKS_DEFAULT_DIR} 의 rulepack_*.json 전부",
    )
    parser.add_argument("--golden", type=Path, default=GOLDEN_DEFAULT, help="골든셋 경로")
    parser.add_argument("--model", choices=("e5", "fake"), default="e5")
    parser.add_argument("--top-k", type=int, default=3, help="L2 가 L3 에 올릴 후보 수")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pack_paths = args.packs or sorted(PACKS_DEFAULT_DIR.glob("rulepack_*.json"))
    if not pack_paths:
        print(f"팩이 없다: {PACKS_DEFAULT_DIR} 에 rulepack_*.json 이 없고 인자도 비었다")
        return 1
    cases = json.loads(args.golden.read_text(encoding="utf-8"))["cases"]
    passage_model, query_model = make_models(args.model)
    for path in pack_paths:
        pack = json.loads(Path(path).read_text(encoding="utf-8"))
        report(pack["pack_version"], evaluate(pack, cases, passage_model, query_model, args.top_k), args.top_k)
    if args.model == "fake":
        print("\nfake 모델은 뜻을 담지 않는다. 위 수치는 품질이 아니라 경로 확인용이다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
