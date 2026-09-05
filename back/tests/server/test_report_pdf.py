"""증빙 리포트 PDF (`services/report_pdf.py` + `/sessions/{id}/report.pdf`).

계약이 `/report`(JSON)와 `/report.pdf` 를 나란히 두고 **같은 내용**을 요구한다. 그래서
값을 만드는 자리를 하나로 두었고(`routers/sessions.py` 의 `_report`), 여기서는 그 약속과
**이 경로가 실제로 열리는지**를 지킨다.

이 경로가 비어 있으면 조용히 틀린다. 상담이 끝나면 서버가 `ended` 에 `report_url` 로 이
주소를 실어 보내고(`ws/endpoint.py`), 화면의 "PDF로 저장" 은 그 값이 있으면 새 탭으로
연다 — 없으면 심사위원이 404 를 본다.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.bootstrap.settings import Settings
from server.main import create_app
from server.services import report_pdf

FIX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


@pytest.fixture
def client() -> TestClient:
    app = create_app(Settings(event_store="memory"))
    with TestClient(app) as c:
        events = json.loads((FIX / "events_scenario_a.json").read_text(encoding="utf-8"))
        store = app.state.runtime.event_store
        for event in events if isinstance(events, list) else events["events"]:
            store.append(event)
        yield c


def _report(client: TestClient) -> tuple[str, dict]:
    session_id = "FIXT-SESS-0A"
    got = client.get(f"/api/sessions/{session_id}/report")
    assert got.status_code == 200, got.text
    return session_id, got.json()


# --- 경로 -----------------------------------------------------------------


def test_the_advertised_report_url_actually_serves_a_pdf(client: TestClient):
    """`ended` 가 알려 주는 그 주소다. 404 면 화면의 저장 버튼이 새 탭에서 404 를 띄운다."""
    session_id, _ = _report(client)
    got = client.get(f"/api/sessions/{session_id}/report.pdf")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("application/pdf")
    assert got.content[:5] == b"%PDF-"


def test_it_opens_in_the_tab_rather_than_downloading(client: TestClient):
    """화면이 새 탭으로 연다. attachment 면 빈 탭만 뜨고 파일이 따로 떨어진다."""
    session_id, _ = _report(client)
    got = client.get(f"/api/sessions/{session_id}/report.pdf")
    assert got.headers["content-disposition"].startswith("inline")
    assert session_id in got.headers["content-disposition"]


def test_an_unknown_session_is_404_not_an_empty_pdf(client: TestClient):
    """빈 PDF 를 주면 증빙이 없는 상담을 있는 것처럼 만든다."""
    assert client.get("/api/sessions/NOPE-0000/report.pdf").status_code == 404


# --- JSON 과 같은 내용인가 --------------------------------------------------


def _text(body: bytes) -> str:
    """구운 PDF 에서 글자를 도로 읽는다.

    바이트를 그대로 뒤지면 안 된다 — reportlab 이 페이지 스트림을 압축해서 ASCII 도
    원문으로 안 남는다. 사람이 볼 때 읽히는지를 재려면 뷰어와 같은 방식으로 뽑아야 한다.
    """
    import io

    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(io.BytesIO(body))
    return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def test_the_pdf_carries_what_the_json_says(client: TestClient):
    """두 경로가 다른 수를 말하면 증빙으로 못 쓴다. 항목 코드가 하나도 빠지면 안 된다."""
    _, report = _report(client)
    text = _text(report_pdf.render(report))
    codes = [row["item_code"] for row in report["sections"]["omission"]]
    assert codes, "fixture 에 누락 축 항목이 없다"
    for code in codes:
        assert code in text, f"{code} 가 PDF 에 없다"


def test_korean_survives_into_the_pdf(client: TestClient):
    """한글이 깨지면 리포트를 아무도 못 읽는다. 항목 이름이 그대로 나와야 한다."""
    _, report = _report(client)
    text = _text(report_pdf.render(report))
    names = [row["name"] for row in report["sections"]["omission"] if row.get("name")]
    assert any(n in text for n in names), f"항목 이름이 하나도 안 보인다: {names[:3]}"


def test_partial_items_say_what_is_missing(client: TestClient):
    """부분 고지의 값어치는 '무엇이 빠졌나' 에 있다. 그것이 빠지면 표가 뜻을 잃는다."""
    _, report = _report(client)
    missing = [
        element
        for row in report["sections"]["omission"]
        for element in (row.get("missing_elements") or [])
    ]
    if not missing:
        pytest.skip("fixture 에 부분 고지가 없다")
    text = _text(report_pdf.render(report))
    assert any(m in text for m in missing)


def test_the_disclaimer_is_always_there(client: TestClient):
    """계약이 리포트에 상시 표기하라고 한 문구다. 판정의 성질을 산출물이 스스로 밝힌다."""
    _, report = _report(client)
    assert report["disclaimer"]
    assert report["disclaimer"][:20] in _text(report_pdf.render(report))


# --- 그리는 쪽 ------------------------------------------------------------


def test_it_renders_without_a_font_file_in_the_repo():
    """한글이 깨지면 리포트가 못 읽히는데, 폰트 파일을 레포에 넣지 않기로 했다.
    reportlab 이 들고 있는 Adobe Korean-1 CID 폰트로 굽는다."""
    body = report_pdf.render(
        {
            "session_id": "S1",
            "pack_version": "DEP-2026.08-v4",
            "sections": {
                "summary": {"items_total": 6, "met": 4},
                "omission": [
                    {
                        "item_code": "DEP-INT-001",
                        "name": "적용 이자율과 우대 조건",
                        "state": "partial",
                        "missing_elements": ["동일 은행 합산"],
                    }
                ],
            },
            "disclaimer": "이해 축은 참고 정보입니다.",
        }
    )
    assert body[:5] == b"%PDF-" and len(body) > 1000


def test_a_report_with_nothing_in_it_still_makes_a_pdf():
    """세션이 비어도 500 을 내면 안 된다 — 화면의 저장 버튼이 그대로 죽는다."""
    assert report_pdf.render({"session_id": "S1"})[:5] == b"%PDF-"


def test_long_lines_wrap_instead_of_running_off_the_page():
    """CID 폰트는 폭을 정확히 못 재서 글자 수로 자른다. 안 자르면 오른쪽으로 흘러 잘린다."""
    assert len(report_pdf._wrap("가" * 200)) > 1
    assert all(len(line) <= report_pdf.WIDTH_CHARS for line in report_pdf._wrap("가" * 200))


def test_a_missing_timestamp_does_not_crash_the_page():
    assert report_pdf._ms(None) == "--:--"
    assert report_pdf._ms(125000) == "02:05"
