from __future__ import annotations

import urllib.request
from dataclasses import replace

import pytest

from regwatch.fetcher import FetchError, HttpFetcher, SafeRedirectHandler
from regwatch.fingerprint import FingerprintError, fingerprint
from regwatch.models import FetchResponse, SourceSpec


class _Headers:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type


class _Response:
    def __init__(self, body: bytes, *, final_url: str, content_type: str = "text/html") -> None:
        self._body = body
        self._offset = 0
        self._final_url = final_url
        self.headers = _Headers(content_type)
        self.status = 200
        self.read_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def geturl(self) -> str:
        return self._final_url


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls = 0

    def open(self, _request, timeout: float):
        assert timeout == 12.0
        self.calls += 1
        return self.response


def _source(**changes) -> SourceSpec:
    base = SourceSpec(
        source_id="official-page",
        category=1,
        title="공식 페이지",
        url="https://example.com/rules",
        mode="html",
        impacts=frozenset({"deposit"}),
        allowed_hosts=frozenset({"example.com"}),
        max_bytes=1_024,
    )
    return replace(base, **changes)


def test_fetcher_rejects_initial_and_redirect_hosts_outside_allowlist() -> None:
    opener = _Opener(_Response(b"ok", final_url="https://evil.example/rules"))
    fetcher = HttpFetcher(opener=opener, timeout_seconds=12.0)

    with pytest.raises(FetchError, match="최종 호스트"):
        fetcher.fetch(_source())
    assert opener.calls == 1

    with pytest.raises(FetchError, match="요청 호스트"):
        fetcher.fetch(_source(url="https://evil.example/rules"))
    assert opener.calls == 1
    with pytest.raises(FetchError, match="HTTPS"):
        fetcher.fetch(_source(url="http://example.com/rules"))
    assert opener.calls == 1


def test_redirect_handler_rejects_unsafe_target_before_following_it() -> None:
    handler = SafeRedirectHandler(_source())
    request = urllib.request.Request("https://example.com/rules")

    with pytest.raises(FetchError, match="리다이렉트 URL"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/rules")

    with pytest.raises(FetchError, match="HTTPS"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://example.com/rules")


def test_fetcher_rejects_non_https_final_url_before_reading_body() -> None:
    response = _Response(b"ok", final_url="http://example.com/rules")
    opener = _Opener(response)

    with pytest.raises(FetchError, match="HTTPS"):
        HttpFetcher(opener=opener, timeout_seconds=12.0).fetch(_source())

    assert response.read_calls == 0


def test_fetcher_stops_reading_after_source_size_limit() -> None:
    opener = _Opener(_Response(b"x" * 1_025, final_url="https://example.com/rules"))

    with pytest.raises(FetchError, match="크기 제한"):
        HttpFetcher(opener=opener, timeout_seconds=12.0).fetch(_source())


def test_pdf_fingerprint_rejects_an_html_error_body() -> None:
    response = FetchResponse(
        body=b"<html>blocked</html>",
        content_type="text/html",
        final_url="https://example.com/rule.pdf",
    )

    with pytest.raises(FingerprintError, match="PDF 서명"):
        fingerprint(_source(mode="pdf"), response)


def test_pdf_fingerprint_rejects_pdf_bytes_with_html_content_type() -> None:
    response = FetchResponse(
        body=b"%PDF-1.7\nfixture",
        content_type="text/html",
        final_url="https://example.com/rule.pdf",
    )

    with pytest.raises(FingerprintError, match="MIME"):
        fingerprint(_source(mode="pdf"), response)


def test_html_fingerprint_ignores_scripts_comments_and_whitespace() -> None:
    left = FetchResponse(
        body=(
            b"<html><body><h1>Rule update</h1><!--x--><script>clock=1</script>"
            b"<a href='/view?id=2'>Open</a></body></html>"
        ),
        content_type="text/html",
        final_url="https://example.com/list",
    )
    right = FetchResponse(
        body=(
            b"<html>\n<body> <h1> Rule   update </h1><script>clock=999</script>"
            b"<a href='https://example.com/view?id=2'> Open </a></body></html>"
        ),
        content_type="text/html",
        final_url="https://example.com/list",
    )

    assert fingerprint(_source(), left).sha256 == fingerprint(_source(), right).sha256


def test_fingerprint_changes_when_visible_content_changes() -> None:
    before = FetchResponse(b"<p>old rule</p>", "text/html", "https://example.com/list")
    after = FetchResponse(b"<p>new rule</p>", "text/html", "https://example.com/list")

    assert fingerprint(_source(), before).sha256 != fingerprint(_source(), after).sha256


def test_html_fingerprint_ignores_view_counts_and_ephemeral_pdf_viewer_tokens() -> None:
    before = FetchResponse(
        body=(
            "<main><span>\uc870\ud68c\uc218 : 39076</span>"
            "<span class='only-m'>\uc870\ud68c\uc218</span>7674"
            "<a href='/ezpdfwv/customLayout.jsp?encdata=AAA'>\ucca8\ubd80</a></main>"
        ).encode(),
        content_type="text/html",
        final_url="https://example.com/list",
    )
    after = FetchResponse(
        body=(
            "<main><span>\uc870\ud68c\uc218 : 39077</span>"
            "<span class='only-m'>\uc870\ud68c\uc218</span>7675"
            "<a href='/ezpdfwv/customLayout.jsp?encdata=BBB'>\ucca8\ubd80</a></main>"
        ).encode(),
        content_type="text/html",
        final_url="https://example.com/list",
    )

    assert fingerprint(_source(), before).sha256 == fingerprint(_source(), after).sha256


def test_fss_board_fingerprint_ignores_trailing_numeric_view_count_cell() -> None:
    before = FetchResponse(
        body=b"<table><tr><td>20799</td><td>title</td><td>7674</td></tr></table>",
        content_type="text/html",
        final_url="https://example.com/list",
    )
    after = FetchResponse(
        body=b"<table><tr><td>20799</td><td>title</td><td>7675</td></tr></table>",
        content_type="text/html",
        final_url="https://example.com/list",
    )

    assert (
        fingerprint(_source(mode="fss_board"), before).sha256
        == fingerprint(_source(mode="fss_board"), after).sha256
    )


def test_html_fingerprint_honors_declared_korean_charset() -> None:
    before = FetchResponse(
        body=("<td>504<span class='only-m'>\uc870\ud68c\uc218</span></td>").encode("euc-kr"),
        content_type="text/html",
        final_url="https://example.com/list",
        encoding="euc-kr",
    )
    after = FetchResponse(
        body=("<td>505<span class='only-m'>\uc870\ud68c\uc218</span></td>").encode("euc-kr"),
        content_type="text/html",
        final_url="https://example.com/list",
        encoding="euc-kr",
    )

    assert fingerprint(_source(), before).sha256 == fingerprint(_source(), after).sha256
