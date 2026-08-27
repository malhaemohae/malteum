from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .models import FetchResponse, ResourceSnapshot, SourceSpec


class FingerprintError(ValueError):
    """응답이 선언된 원천 형식과 다름."""


_SPACE = re.compile(r"\s+")
_VIEW_COUNT = re.compile(r"^\uc870\ud68c\uc218\s*:\s*\d+$")
_VIEW_LABEL = "\uc870\ud68c\uc218"
_PDF_CONTENT_TYPES = frozenset({"application/pdf", "application/octet-stream"})


def _canonical_url(base_url: str, href: str) -> str:
    absolute = urljoin(base_url, href)
    parts = urlsplit(absolute)
    if parts.path.endswith("/ezpdfwv/customLayout.jsp"):
        query = ""
    else:
        query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


class _VisibleHtml(HTMLParser):
    def __init__(self, base_url: str, *, ignore_trailing_numeric_cell: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._skip_depth = 0
        self._ignore_trailing_numeric_cell = ignore_trailing_numeric_cell
        self._row_cells: list[list[tuple[str, str]]] | None = None
        self._cell_tokens: list[tuple[str, str]] | None = None
        self.tokens: list[tuple[str, str]] = []

    def _append(self, token: tuple[str, str]) -> None:
        target = self._cell_tokens if self._cell_tokens is not None else self.tokens
        target.append(token)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "tr":
            self._row_cells = []
        if lowered == "td":
            self._cell_tokens = []
        if lowered in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth or lowered != "a":
            return
        href = dict(attrs).get("href")
        if href and not href.lower().startswith(("javascript:", "mailto:", "tel:")):
            self._append(("link", _canonical_url(self._base_url, href)))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "td" and self._cell_tokens is not None:
            cell = self._cell_tokens
            self._cell_tokens = None
            if ("text", _VIEW_LABEL) in cell:
                cell = [
                    token for token in cell if not (token[0] == "text" and token[1].isdecimal())
                ]
            if self._row_cells is None:
                self.tokens.extend(cell)
            else:
                self._row_cells.append(cell)
        if tag.lower() == "tr" and self._row_cells is not None:
            cells = self._row_cells
            self._row_cells = None
            if (
                self._ignore_trailing_numeric_cell
                and cells
                and len(cells[-1]) == 1
                and cells[-1][0][0] == "text"
                and cells[-1][0][1].isdecimal()
            ):
                cells.pop()
            for cell in cells:
                self.tokens.extend(cell)
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        normalized = _SPACE.sub(" ", data).strip()
        if _VIEW_COUNT.fullmatch(normalized):
            normalized = _VIEW_LABEL
        if normalized.isdecimal() and self.tokens and self.tokens[-1] == ("text", _VIEW_LABEL):
            return
        if normalized:
            self._append(("text", normalized))


def _html_bytes(response: FetchResponse, *, ignore_trailing_numeric_cell: bool = False) -> bytes:
    parser = _VisibleHtml(
        response.final_url, ignore_trailing_numeric_cell=ignore_trailing_numeric_cell
    )
    try:
        parser.feed(response.body.decode(response.encoding or "utf-8", errors="replace"))
    except LookupError as exc:
        raise FingerprintError(f"unsupported encoding: {response.encoding}") from exc
    parser.close()
    return json.dumps(parser.tokens, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def fingerprint(source: SourceSpec, response: FetchResponse) -> ResourceSnapshot:
    if source.mode == "pdf":
        if not response.body.lstrip().startswith(b"%PDF-"):
            raise FingerprintError(f"PDF 서명이 없음: {source.source_id}")
        if response.content_type.lower() not in _PDF_CONTENT_TYPES:
            raise FingerprintError(
                f"PDF MIME 타입이 아님: {source.source_id}: {response.content_type}"
            )
        canonical = response.body
    elif source.mode in {"html", "fss_board"}:
        canonical = _html_bytes(response, ignore_trailing_numeric_cell=source.mode == "fss_board")
    else:
        raise FingerprintError(f"지원하지 않는 mode: {source.mode}")

    return ResourceSnapshot(
        source_id=source.source_id,
        sha256=hashlib.sha256(canonical).hexdigest(),
        size_bytes=len(response.body),
        final_url=response.final_url,
        content_type=response.content_type,
        encoding=response.encoding,
    )
