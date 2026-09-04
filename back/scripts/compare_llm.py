#!/usr/bin/env python3
"""L3 모델 비교 실측 (DESIGN D4). judge_cases 의 L3 케이스를 모델마다 여러 번 돌려 표로 만든다.

정답: 기대 verdict(item·axis·state·missing_elements)가 전부 나옴. 여분: 기대에 없는 verdict 수.
L2 는 fake 임베더(후보 선별은 모델과 무관). 키·provider 는 루트 .env 의 APP_LLM_* 를 쓴다.

    uv run python scripts/compare_llm.py                       # 기본 후보 전부
    uv run python scripts/compare_llm.py qwen/qwen3-32b openai/gpt-oss-20b --runs 3
    uv run python scripts/compare_llm.py --no-reasoning        # OpenRouter reasoning 끄고
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.simplefilter("ignore")

from engine.adapters.cache.memory import MemoryDecisionCache  # noqa: E402
from engine.adapters.llm.litellm import LiteLlmJudge  # noqa: E402
from engine.adapters.vector_index.memory import MemoryVectorIndex  # noqa: E402
from engine.build import build_engine  # noqa: E402
from server.bootstrap.settings import Settings  # noqa: E402
from tests.engine.conftest import FIX, PACK_VERSION  # noqa: E402
from tests.engine.fakes import FakeChunkIndex, FakeEmbedder, FakePackSource  # noqa: E402
from tests.engine.test_judge_cases import CASES, PHRASES, _run  # noqa: E402

# 30B 이하(오픈 가중치, tool calling 지원)가 기준. qwen3-32b 는 첫 실측 기준선으로만 둔다
DEFAULT_MODELS = [
    "qwen/qwen3-32b",
    "qwen/qwen3-30b-a3b",
    "qwen/qwen3-30b-a3b-instruct-2507",
    "qwen/qwen3-14b",
    "qwen/qwen3-8b",
    "qwen/qwen3.5-27b",
    "qwen/qwen3.5-9b",
    "qwen/qwen3.6-27b",
    "qwen/qwen3.8-27b",
    "google/gemma-3-27b-it",
    "google/gemma-3-12b-it",
    "google/gemma-4-26b-a4b-it",
    "mistralai/mistral-small-3.2-24b-instruct",
    "mistralai/ministral-14b-2512",
    "mistralai/ministral-8b-2512",
    "mistralai/mistral-nemo",
    "openai/gpt-oss-20b",
    "meta-llama/llama-3.1-8b-instruct",
    "nvidia/nemotron-3-nano-30b-a3b",
    "ibm-granite/granite-4.1-8b",
]
L3_CASES = [c for c in CASES if "utterance" in c and c["expect"]["tier"] == "L3"]


def _expected(case) -> set[tuple]:
    out = set()
    for ev in case["expect"]["verdicts"]:
        if ev.get("decided_by", "L3") == "L3":
            out.add(
                (ev["item_code"], ev["axis"], ev["state"], tuple(ev.get("missing_elements", ())))
            )
    return out


def _actual(result) -> set[tuple]:
    return {(v.item_code, v.axis, v.state, tuple(v.missing_elements)) for v in result.verdicts}


class _capture_llm_errors(logging.Handler):
    """engine 로거의 'L3 호출 실패' 경고에서 사유를 뽑는다."""

    def __init__(self, sink: list[str]) -> None:
        super().__init__(logging.WARNING)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "L3" in msg:
            self.sink.append(msg)

    def __enter__(self):
        logging.getLogger("engine").addHandler(self)
        return self

    def __exit__(self, *exc):
        logging.getLogger("engine").removeHandler(self)


def run_model(model: str, settings: Settings, runs: int, no_reasoning: bool) -> dict:
    import json

    pack_json = json.loads((FIX / f"rulepack_{PACK_VERSION}.json").read_text(encoding="utf-8"))
    codes = [it["code"] for it in pack_json["items"]]
    rows = []
    for _ in range(runs):
        embedder = FakeEmbedder(codes, PHRASES)
        engine = build_engine(
            FakePackSource(pack_json),
            embedder,
            MemoryVectorIndex(),
            FakeChunkIndex([], embedder),
            LiteLlmJudge(
                model,
                provider=settings.llm_provider,
                api_key=settings.llm_api_key,
                timeout_s=90,
                extra_body={"reasoning": {"enabled": False}} if no_reasoning else None,
            ),
            MemoryDecisionCache(),  # 실행마다 새로 만들어 캐시가 두 번째 실행을 가리지 않게
            l3_budget_ms=120_000,
        )
        pack = engine.load_pack(PACK_VERSION)
        for case in L3_CASES:
            results, _, _ = _run(engine, pack, case)
            second = results[1] if len(results) == 2 else None
            if second is None or not second.trace.l3_called or second.trace.llm_tokens is None:
                rows.append(
                    {
                        "case": case["name"],
                        "ok": False,
                        "extra": 0,
                        "ms": None,
                        "tok": None,
                        "err": True,
                    }
                )
                continue
            exp, act = _expected(case), _actual(second)
            rows.append(
                {
                    "case": case["name"],
                    "ok": exp <= act,
                    "extra": len(act - exp),
                    "ms": second.trace.l3_ms,
                    "tok": second.trace.llm_tokens,
                    "err": False,
                    "got": sorted(act),
                }
            )
    ms = [r["ms"] for r in rows if r["ms"] is not None]
    tok = [r["tok"] for r in rows if r["tok"] is not None]
    return {
        "model": model,
        "pass": sum(r["ok"] for r in rows),
        "total": len(rows),
        "errors": sum(r["err"] for r in rows),
        "extra": sum(r["extra"] for r in rows),
        "p50_ms": statistics.median(ms) if ms else None,
        "max_ms": max(ms) if ms else None,
        "tok": statistics.mean(tok) if tok else None,
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", default=DEFAULT_MODELS)
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--no-reasoning", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="케이스별 실제 verdict 출력")
    a = ap.parse_args()
    settings = Settings()
    if not settings.llm_api_key:
        sys.exit("APP_LLM_API_KEY 없음 (루트 .env)")
    with ThreadPoolExecutor(max_workers=4) as ex:
        reports = list(ex.map(lambda m: run_model(m, settings, a.runs, a.no_reasoning), a.models))
    n = len(L3_CASES) * a.runs
    reasoning = "off" if a.no_reasoning else "default"
    print(
        f"\nL3 {len(L3_CASES)}건 × {a.runs}회 = {n}, "
        f"provider={settings.llm_provider}, reasoning={reasoning}\n"
    )
    print("| 모델 | 정답 | 여분 verdict | 오류 | p50 ms | max ms | 평균 토큰 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in sorted(reports, key=lambda r: (-r["pass"], r["extra"], r["p50_ms"] or 9e9)):
        f = lambda v: "-" if v is None else f"{v:.0f}"  # noqa: E731
        print(
            f"| {r['model']} | {r['pass']}/{r['total']} | {r['extra']} | {r['errors']} "
            f"| {f(r['p50_ms'])} | {f(r['max_ms'])} | {f(r['tok'])} |"
        )
    if a.verbose:
        for r in reports:
            print(f"\n## {r['model']}")
            for row in r["rows"]:
                mark = "ERR" if row["err"] else ("ok " if row["ok"] else "X  ")
                print(f"  {mark} {row['case']}: {row.get('got', '-')}")
    failed = [r for r in reports if r["pass"] < r["total"]]
    if failed and not a.verbose:
        print("\n(틀린 케이스의 실제 verdict 는 --verbose 로)")


if __name__ == "__main__":
    main()
