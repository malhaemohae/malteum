"""근거 원문(기능 ⑭)이 돌려주는 페이지 이미지 주소.

`doc_id` 가 `05_상품설명서_정기예금` 처럼 한국어라, 만들어 주는 주소가 ASCII 가 아니면
클라이언트에 따라 요청 자체가 안 나간다. 그 주소로 실제 경로가 다시 풀리는지까지 본다.
"""

from urllib.parse import unquote, urlparse

from server.routers.evidence import _page_image_url

DOC_ID = "05_상품설명서_정기예금"


def test_page_image_url_is_ascii_and_round_trips():
    url = _page_image_url(DOC_ID, 3)
    assert url.isascii(), f"한국어가 그대로 남았다: {url}"
    assert url.endswith("/pages/3.png")
    # 인코딩을 풀면 원래 doc_id 가 나와야 한다. 라우터가 그 값으로 파일을 찾는다
    segment = urlparse(url).path.split("/pages/")[0].rsplit("/", 1)[1]
    assert unquote(segment) == DOC_ID


def test_slash_in_doc_id_cannot_escape_the_path():
    """경로 조각이라 `/` 도 인코딩한다. 안 그러면 doc_id 가 경로를 한 칸 더 파고든다."""
    url = _page_image_url("a/b", 1)
    assert url == "/api/documents/a%2Fb/pages/1.png"
