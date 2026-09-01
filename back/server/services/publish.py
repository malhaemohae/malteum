"""팩 발행. 스키마 검증 → 근거 스팬 대조(P4) → 저장.

계약: "M3 가 호출한다. 승인 완료 항목만 담아 새 버전으로 굳힌다. **기존 버전은 절대
덮어쓰지 않는다** — 진행 중 세션이 그 버전을 보고 있을 수 있다."

**422 가 이 경로의 존재 이유다.** 계약이 근거 스팬이 원문과 불일치하는 항목을 P4 위반으로
거절하라고 정했다. 그 대조를 `contracts/find_span.py` 로 한다 — 계약 README 가 "좌표를
뜨는 함수는 하나다. M3 의 발행 파이프라인도 이 함수를 써야 한다. 다른 구현을 쓰면 그쪽에서는
통과하고 여기서는 실패하는 팩이 나온다. 그래서 이 파일은 도구가 아니라 계약이다" 라고
못박았다. 같은 함수를 쓰므로 M3 가 통과시킨 팩은 여기서도 통과한다.

여기는 `rulepack` 을 부르지 않는다(import-linter). 서명·승인 같은 M3 내부 무결성은
`scripts/load_pack.py` 가 보고, 이 경로는 계약이 요구한 세 가지만 본다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


class PublishRejected(Exception):
    """422. 어느 항목이 왜 걸렸는지 함께 올린다."""

    def __init__(self, rejected: list[dict[str, str]]) -> None:
        super().__init__(f"근거가 원문과 맞지 않는 항목 {len(rejected)}건")
        self.rejected = rejected


class PublishInvalid(Exception):
    """400. 계약 스키마를 만족하지 않는다."""


@dataclass(frozen=True, slots=True)
class Published:
    pack_version: str
    item_count: int
    embedding_indexed: int


@cache
def _validator() -> Draft202012Validator:
    schema = json.loads((CONTRACTS / "rulepack.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


@cache
def _find_span():
    """계약의 함수를 그대로 쓴다. `contracts/` 는 패키지가 아니라 파일로 얹어 읽는다."""
    spec = importlib.util.spec_from_file_location("malteum_find_span", CONTRACTS / "find_span.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("contracts/find_span.py 로드 실패")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.find_span


def verify_evidence(doc: dict[str, Any], docs_dir: Path) -> list[dict[str, str]]:
    """항목마다 인용 문자열이 그 원문 그 페이지에 실재하는지 본다 (P4).

    원문이 없는 것도 거절한다. 근거를 확인할 수 없는 항목은 근거가 없는 항목과 같다.
    """
    find_span = _find_span()
    rejected: list[dict[str, str]] = []
    for item in doc.get("items", []):
        evidence = item.get("evidence") or {}
        span, doc_id, page = evidence.get("span"), evidence.get("doc_id"), evidence.get("page")
        if not (span and doc_id):
            rejected.append({"item_code": item.get("code", "?"), "reason": "근거가 비어 있음"})
            continue
        pdf = docs_dir / f"{doc_id}.pdf"
        if not pdf.is_file():
            rejected.append({"item_code": item["code"], "reason": f"원문이 없음: {doc_id}"})
            continue
        try:
            hit = find_span(str(pdf), span, page)
        except Exception as e:  # noqa: BLE001  없는 쪽수를 주면 pypdfium2 가 던진다
            # 대조를 못 한 것도 거절이다. 여기서 예외를 올리면 422 가 500 이 되고,
            # 화면은 "우리 잘못" 과 "근거가 틀렸다" 를 구분하지 못한다
            rejected.append(
                {"item_code": item["code"], "reason": f"{doc_id} p{page} 를 열 수 없음: {e}"}
            )
            continue
        if hit is None:
            rejected.append(
                {"item_code": item["code"], "reason": f"{doc_id} p{page} 에 그 문장이 없음"}
            )
    return rejected


def validate(doc: Any) -> None:
    if not isinstance(doc, dict):
        raise PublishInvalid("팩은 객체여야 합니다.")
    errors = [e.message for e in _validator().iter_errors(doc)]
    if errors:
        raise PublishInvalid("; ".join(errors)[:400])
