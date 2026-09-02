"""REST 오류를 계약 `Error` 모양으로 바꾼다.

계약이 이유를 적어 두었다 — "ws_protocol 의 error.code 와 같은 집합을 쓴다. **두 경로에서
코드가 갈라지면 프런트가 분기를 두 번 짠다.**" FastAPI 기본값은 `{"detail": "..."}` 라
그대로 두면 화면이 REST 와 ws 에서 다른 모양을 받는다.

`HTTPException` 을 그대로 쓰고 여기서 상태 코드를 계약 enum 으로 옮긴다. 라우터마다
코드를 손으로 적으면 빠뜨리는 곳이 생기고, 그 빠뜨림은 화면에서야 드러난다.

**starlette 의 HTTPException 에 건다.** fastapi.HTTPException 은 그 자식이라, 자식에만
걸면 라우팅이 직접 내는 404(없는 경로)·405(메서드 틀림)가 핸들러를 비껴가 `{"detail":
"Not Found"}` 로 나간다. 프런트가 오타 하나로 계약 밖 모양을 받는 자리다.

**처리 못 한 예외도 계약 모양으로 낸다.** 기본값은 `Content-Type: text/plain` 에 본문이
`Internal Server Error` 라 화면의 `res.json()` 이 파싱 단계에서 터진다. 계약 enum 에
`internal` 이 있는 이유가 이 자리고, 5xx 는 `retryable: true` 여야 재시도가 붙는다.
사고 내용은 서버 로그에만 남긴다 — 스택은 화면에 나갈 것이 아니다.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

log = logging.getLogger(__name__)

# 계약 components.schemas.Error.code. ws 6종 + REST 3종
BY_STATUS = {
    400: "validation_failed",
    401: "validation_failed",
    403: "validation_failed",
    404: "not_found",
    405: "validation_failed",
    409: "conflict",
    415: "validation_failed",
    422: "validation_failed",
    429: "rate_limited",
}

# starlette 라우팅이 직접 내는 문구. 나머지 메시지가 전부 한국어라 여기만 영어면
# 화면에 그대로 뜬다 (프런트는 message 를 사용자에게 보여준다)
ROUTING_MESSAGE = {
    "Not Found": "요청한 경로가 없습니다.",
    "Method Not Allowed": "이 경로가 받지 않는 메서드입니다.",
}


def _body(status: int, message: str, detail: Any = None) -> dict[str, Any]:
    # 표에 없는 4xx 는 요청 탓이다. internal 로 떨어뜨리면 화면이 서버 사고로 읽는다
    fallback = "validation_failed" if 400 <= status < 500 else "internal"
    out: dict[str, Any] = {
        "code": BY_STATUS.get(status, fallback),
        "message": message,
        # 5xx 는 다시 걸어 볼 만하다. 4xx 는 같은 요청을 다시 보내도 같은 답이다
        "retryable": status >= 500,
    }
    if detail is not None:
        out["detail"] = detail
    return out


def install(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        # 라우터가 dict 를 넘기면 그 안에 code·message 가 있을 수 있다(422 rejected_items)
        if isinstance(exc.detail, dict):
            body = _body(exc.status_code, exc.detail.get("message", ""), exc.detail)
            body["code"] = exc.detail.get("code") or body["code"]
        else:
            text = str(exc.detail)
            body = _body(exc.status_code, ROUTING_MESSAGE.get(text, text))
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            _body(422, "요청이 계약과 맞지 않습니다.", {"errors": exc.errors()[:5]}),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("처리하지 못한 예외: %s %s", request.method, request.url.path)
        return JSONResponse(_body(500, "서버가 요청을 처리하지 못했습니다."), status_code=500)
