"""팩 발행의 P4 관문. 인용이 원문에 실재하지 않으면 팩째로 거절한다.

계약 README: "좌표를 뜨는 함수는 `find_span.py` 하나다. M3 의 팩 발행 파이프라인도 이
함수를 써야 한다. 다른 구현을 쓰면 그쪽에서는 통과하고 여기서는 실패하는 팩이 나온다."
같은 함수를 쓰는지가 이 테스트의 요점이다.
"""

import copy
import json
from pathlib import Path

import pytest

from server.bootstrap.settings import Settings
from server.services.publish import PublishInvalid, validate, verify_evidence

FIX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
PACK = json.loads((FIX / "rulepack_DEP-2026.08-v6.json").read_text(encoding="utf-8"))
DOCS = Settings().docs_dir


def test_real_pack_passes_the_evidence_gate():
    """발행된 팩의 인용은 원문에 실재해야 한다. 아니면 화면에 그럴듯한 가짜가 뜬다."""
    assert verify_evidence(PACK, DOCS) == []


def test_tampered_span_is_rejected():
    doc = copy.deepcopy(PACK)
    doc["items"][0]["evidence"]["span"] = "원문에 없는 문장입니다"
    rejected = verify_evidence(doc, DOCS)
    assert [r["item_code"] for r in rejected] == [doc["items"][0]["code"]]
    assert "없음" in rejected[0]["reason"]


def test_wrong_page_is_rejected():
    """페이지가 틀리면 형광펜이 엉뚱한 곳에 그려진다. 좌표가 근거의 일부다."""
    doc = copy.deepcopy(PACK)
    doc["items"][0]["evidence"]["page"] = 99
    assert verify_evidence(doc, DOCS)


def test_missing_source_document_is_rejected():
    """근거를 확인할 수 없는 항목은 근거가 없는 항목과 같다."""
    doc = copy.deepcopy(PACK)
    doc["items"][0]["evidence"]["doc_id"] = "99_없는문서"
    rejected = verify_evidence(doc, DOCS)
    assert "원문이 없음" in rejected[0]["reason"]


def test_schema_is_checked_before_evidence():
    with pytest.raises(PublishInvalid):
        validate({"pack_version": "X"})
    with pytest.raises(PublishInvalid):
        validate("팩이 아님")
    validate(PACK)  # 실물은 통과
