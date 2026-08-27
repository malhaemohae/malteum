from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

from .models import FetchResponse, SourceSpec


class FetchError(RuntimeError):
    """공식 원천을 안전 계약 안에서 가져오지 못함."""


def _ensure_safe_url(url: str, source: SourceSpec, *, purpose: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise FetchError(f"{purpose} URL은 HTTPS여야 함: {url}")
    host = (parsed.hostname or "").lower()
    if host not in source.allowed_hosts:
        raise FetchError(f"{purpose} 호스트가 허용 목록 밖임: {host}")


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, source: SourceSpec) -> None:
        self._source = source

    def redirect_request(
        self,
        request,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        target = urljoin(request.full_url, newurl)
        _ensure_safe_url(target, self._source, purpose="리다이렉트 URL")
        return super().redirect_request(request, fp, code, msg, headers, target)


class HttpFetcher:
    def __init__(self, *, opener=None, timeout_seconds: float = 30.0) -> None:
        self._opener = opener
        self._timeout_seconds = timeout_seconds

    def fetch(self, source: SourceSpec) -> FetchResponse:
        _ensure_safe_url(source.url, source, purpose="요청")

        request = urllib.request.Request(
            source.url,
            headers={
                "Accept": "application/pdf,text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                "User-Agent": "Guitteum-Regwatch/0.1 (+official-source-monitor)",
            },
        )
        try:
            opener = self._opener or urllib.request.build_opener(SafeRedirectHandler(source))
            with opener.open(request, timeout=self._timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if not 200 <= status < 300:
                    raise FetchError(f"HTTP 상태 오류: {status}")
                final_url = response.geturl()
                _ensure_safe_url(final_url, source, purpose="최종")
                body = response.read(source.max_bytes + 1)
                if len(body) > source.max_bytes:
                    raise FetchError(f"응답 크기 제한 초과: {source.source_id}")
                content_type = response.headers.get_content_type()
                charset_reader = getattr(response.headers, "get_content_charset", None)
                encoding = charset_reader() if charset_reader else None
        except FetchError:
            raise
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            raise FetchError(f"원천 요청 실패: {source.source_id}: {exc}") from exc

        return FetchResponse(
            body=body, content_type=content_type, final_url=final_url, encoding=encoding
        )
