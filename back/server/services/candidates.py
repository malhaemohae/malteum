"""항목 후보. 계약 `GET /documents/{doc_id}/candidates` 가 돌려주는 것.

계약이 이 경로의 존재 이유를 적어 두었다 — "추출 결과에서 뽑은 규정 항목 후보. 아직 팩이
아니다. **사람이 승인해야 팩에 들어간다. 이 경계가 P4 를 지키는 지점이다.**"

## 후보를 어디서 가져오나

M3 의 후보 규칙(`rulepack/config/candidate_rules.json`)을 읽는다. **import 가 아니라
파일 읽기다** — `server → rulepack` 은 import-linter 가 막지만(`pyproject.toml`), 여기서
필요한 것은 코드가 아니라 값이다. 경로는 `settings.candidate_rules` 하나에만 둔다
(AGENTS.md 원칙 3: 이름·주소·설정은 한 곳에만).

그 파일을 고르는 이유는 계약이 요구하는 필드가 거기 다 있기 때문이다.

    code → suggested_code · name · type · requirements → requirement_elements
    doc_id · page · span → evidence

**대가를 적어 둔다.** M3 가 그 파일을 옮기거나 모양을 바꾸면 이 경로가 조용히 빈 목록을
낸다. 그래서 `tests/server/test_candidates.py` 가 실물 파일의 존재와 모양을 함께 본다 —
조용히 비는 대신 테스트가 먼저 깨지게.

## 대조는 계약 함수로

`span_verified` 는 `contracts/find_span.py` 로 뜬다. 계약 README 가 "좌표를 뜨는 함수는
하나다. 다른 구현을 쓰면 그쪽에서는 통과하고 여기서는 실패하는 팩이 나온다. 그래서 이
파일은 도구가 아니라 계약이다" 라고 못박았다. M3 파이프라인도 같은 함수를 쓰므로 판정이
갈리지 않는다 — 실측으로 19 통과 / 2 폐기가 M3 의 `docs/STATUS.md` 와 일치했다.

폐기되는 2건(`DEP-REJ-001` · `LOAN-REJ-001`)은 M3 가 심어 둔 부정 표본이고, 기획 8.2 가
S4 화면에 요구하는 "**자동 폐기 행 노출**(P4 의 시각 증거)" 이 정확히 이 둘이다. 걸러서
숨기지 않고 `status="rejected"` 로 함께 내보낸다.

## 계약 밖 type 은 내보내지 않는다

허용 집합은 `_contract_types()` 가 계약에서 읽는다. 손으로 적으면 계약이 늘 때 코드가
뒤처지고, 줄 때는 아무도 모른 채 계약 밖 값이 나간다.

계약이 2026-09-02 에 `risk` 를 받게 되어(`rulepack.schema.json` 과 같은 집합) 지금은
빠지는 항목이 없다. 그래도 이 걸름은 남겨 둔다 — M3 가 새 type 을 먼저 쓰기 시작하면
계약이 따라올 때까지 여기서 막힌다. 타입을 다른 값으로 바꿔 내보내는 길은 택하지 않는다.
기획 7.1 이 위험 신호를 "고객 발화 대상, 판정이 아니라 경보" 로 두었는데 다른 type 으로
보내면 화면이 다른 축으로 그린다. 속이느니 빠지고 로그에 남기는 편이 낫다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from server.services.publish import load_find_span

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"

log = logging.getLogger(__name__)


class CandidateNotFound(LookupError):
    """404. 그 문서에 그 후보가 없다."""


@cache
def _contract_types() -> frozenset[str]:
    """계약이 허용하는 후보 `type`. 손으로 적지 않고 계약에서 읽는다 — 계약이 늘면
    코드를 안 고쳐도 따라가고, 줄면 테스트가 먼저 깨진다."""
    spec = yaml.safe_load((CONTRACTS / "api.openapi.yaml").read_text(encoding="utf-8"))
    schema = spec["paths"]["/documents/{doc_id}/candidates"]["get"]["responses"]["200"]
    item = schema["content"]["application/json"]["schema"]["properties"]["candidates"]["items"]
    return frozenset(item["properties"]["type"]["enum"])


def candidate_id(doc_id: str, code: str) -> str:
    """문서와 항목 코드로 결정된다.

    무작위로 매기면 파이프라인을 다시 돌릴 때마다 id 가 바뀌어, 어제 승인한 후보가
    오늘은 다른 후보가 된다. 승인 기록은 이 id 로 남으므로 재실행을 견뎌야 한다.
    """
    return hashlib.sha256(f"{doc_id}:{code}".encode()).hexdigest()[:16]


def _rules(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [rule for rules in doc.get("products", {}).values() for rule in rules]


def _pdf(docs_dir: Path, doc_id: str) -> Path | None:
    # doc_id 가 경로가 되지 않게 막는다. URL 로 들어오는 값이다(services/documents.py 와 같은 규칙)
    if "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        return None
    path = docs_dir / f"{doc_id}.pdf"
    return path if path.exists() else None


def for_document(
    doc_id: str,
    *,
    rules_path: Path,
    docs_dir: Path,
    approved: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """그 문서에서 뽑힌 후보들. 계약 모양 그대로.

    `approved` 는 승인 기록(candidate_id → 기록). 승인된 후보는 `status="approved"` 가
    되고 검수자가 고친 내용(`edits`)이 원래 값 위에 얹힌다 — 화면이 승인 후에도 같은
    경로를 다시 읽기 때문이다.
    """
    approved = approved or {}
    find_span = load_find_span()
    pdf = _pdf(docs_dir, doc_id)

    candidates: list[dict[str, Any]] = []

    for rule in _rules(rules_path):
        if rule.get("doc_id") != doc_id:
            continue
        if rule.get("type") not in _contract_types():
            log.warning(
                "계약 후보 type 밖이라 목록에서 뺍니다: %s (type=%r, doc_id=%s). "
                "api.openapi.yaml 의 후보 type 에 그 값이 추가되면 자동으로 따라갑니다.",
                rule.get("code", "?"),
                rule.get("type"),
                doc_id,
            )
            continue

        page, span = rule.get("page"), rule.get("span")
        # 원문이 없으면 대조 자체가 불가능하다. 확인할 수 없는 근거는 없는 근거와 같다(P4)
        hit = find_span(str(pdf), span, page) if (pdf and span and page) else None
        evidence: dict[str, Any] = {"page": page, "span": span}
        if hit:
            evidence["bbox"] = hit["bbox"]

        cid = candidate_id(doc_id, rule["code"])
        record = approved.get(cid)
        edits = (record or {}).get("edits") or {}
        candidate = {
            "candidate_id": cid,
            "suggested_code": rule["code"],
            "name": edits.get("name") or rule.get("name", ""),
            "type": rule["type"],
            "requirement_elements": edits.get("requirement_elements")
            or rule.get("requirements", []),
            "evidence": evidence,
            "span_verified": hit is not None,
            # 자동 폐기를 숨기지 않는다. 기획 8.2 가 S4 에 요구하는 P4 의 시각 증거다
            "status": "approved" if record else ("pending" if hit else "rejected"),
        }
        candidates.append(candidate)

    return {"candidates": candidates}


def one(doc_id: str, cid: str, *, rules_path: Path, docs_dir: Path) -> dict[str, Any]:
    """후보 하나. 승인 경로가 대상을 확인할 때 쓴다."""
    for candidate in for_document(doc_id, rules_path=rules_path, docs_dir=docs_dir)["candidates"]:
        if candidate["candidate_id"] == cid:
            return candidate
    raise CandidateNotFound(cid)
