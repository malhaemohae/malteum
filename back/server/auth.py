"""쓰기 경로의 토큰. 계약 `securitySchemes.bearerAuth` 가 정한 범위만.

계약: "쓰기 경로에만 요구한다. 심사위원이 로그인 없이 시연할 수 있어야 하므로 조회·세션
시작은 security 를 비워 두고, **문서 업로드·후보 승인·팩 발행만 토큰을 요구한다.**
토큰은 환경변수 한 개로 관리한다 (MVP 범위. 사용자 계정 체계 없음)."

**토큰이 설정되지 않으면 거절한다.** 통과시키면 배포에서 누구나 팩을 발행할 수 있고,
팩은 불변 발행물이라 잘못 들어간 버전은 지울 수 없다. 열어 두는 쪽이 편하지만 그 편함의
대가를 심사 중에 치른다. 발행이 필요한 쪽(M3)은 `scripts/load_pack.py` 로 DB 에 직접
넣는 경로가 따로 있어, 막아도 막히는 일이 없다.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request


def require_token(request: Request) -> None:
    """`Authorization: Bearer <토큰>`. 계약이 지정한 경로에만 건다."""
    configured = request.app.state.settings.admin_token
    if not configured:
        raise HTTPException(401, "쓰기 경로에는 APP_ADMIN_TOKEN 이 설정돼 있어야 합니다.")
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    # 상수 시간 비교. 문자열 == 는 앞에서부터 갈려 응답 시간이 토큰을 조금씩 흘린다
    if scheme.lower() != "bearer" or not secrets.compare_digest(token, configured):
        raise HTTPException(401, "토큰이 없거나 맞지 않습니다.")
