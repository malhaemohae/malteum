"""근거 원문 PDF 를 페이지 이미지로 준다 (기능 ⑭ 오버레이의 배경).

**외부 링크로 보내지 않고 우리가 렌더한다.** 계약이 그 이유를 적어 두었다 — 문서가 개정돼도
과거 근거가 그대로 보여야 하기 때문이다. 좌표(bbox)도 우리가 준 페이지 이미지 기준이어야
화면이 형광펜을 정확히 얹는다.

PNG 인코딩을 손으로 하는 이유: Pillow 가 의존성에 없다. 넣으려면 공용 pyproject 와
uv.lock 을 고쳐야 하고 그건 팀 합의 사항이다. 여기서 쓰는 건 무압축이 아니라 zlib 를
쓰는 표준 PNG 이며, 팀이 Pillow 를 들이면 이 함수만 갈아끼우면 된다.

이 파일은 **렌더만** 한다. 업로드·추출·후보 승인(M3 파이프라인)은 오너가 정해지지 않았고
여기 없다.
"""

from __future__ import annotations

import struct
import zlib
from functools import lru_cache
from pathlib import Path

import pypdfium2 as pdfium

MAX_SCALE = 4.0


class DocumentNotFound(LookupError):
    pass


def _path(docs_dir: Path, doc_id: str) -> Path:
    # doc_id 가 경로가 되지 않게 막는다. 팩이 주는 값이지만 URL 로도 들어온다
    if "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        raise DocumentNotFound(doc_id)
    path = docs_dir / f"{doc_id}.pdf"
    if not path.exists():
        raise DocumentNotFound(doc_id)
    return path


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def _png(rgb: bytes, width: int, height: int) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8bit truecolor
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride : (y + 1) * stride] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


@lru_cache(maxsize=64)
def page_size(docs_dir: Path, doc_id: str, page: int) -> tuple[float, float]:
    """PDF 포인트 단위 (width, height). 화면이 bbox 를 이미지 좌표로 바꿀 때 쓴다."""
    pdf = pdfium.PdfDocument(str(_path(docs_dir, doc_id)))
    if not 1 <= page <= len(pdf):
        raise DocumentNotFound(f"{doc_id} p{page}")
    return tuple(pdf[page - 1].get_size())  # type: ignore[return-value]


@lru_cache(maxsize=64)
def render(docs_dir: Path, doc_id: str, page: int, scale: float) -> bytes:
    """계약: 렌더 결과를 캐시한다. 같은 페이지를 여러 판정이 함께 가리킨다."""
    pdf = pdfium.PdfDocument(str(_path(docs_dir, doc_id)))
    if not 1 <= page <= len(pdf):
        raise DocumentNotFound(f"{doc_id} p{page}")
    bitmap = pdf[page - 1].render(scale=min(max(scale, 0.1), MAX_SCALE), rev_byteorder=True)
    buffer, channels = bytes(bitmap.buffer), bitmap.n_channels
    if channels == 3:
        rgb = buffer
    else:  # RGBA 에서 알파를 뗀다
        rgb = b"".join(buffer[i : i + 3] for i in range(0, len(buffer), channels))
    return _png(rgb, bitmap.width, bitmap.height)
