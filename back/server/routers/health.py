from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict:
    """부분 장애를 구분한다(계약). stt 가 죽어도 text 모드는 살아 있다.

    9/7~9/11 접속 보장의 외부 감시가 이 값을 본다. 저장소가 죽었는데 ok 를 돌려주면
    감시가 무력해지므로 db 는 실제로 찔러 본다.
    """
    runtime = request.app.state.runtime
    settings = request.app.state.settings
    # 설정 여부만 본다. 외부 API 를 찔러 보면 감시가 10초마다 유료 호출을 낸다.
    # db 만 실제로 찌르는 이유는 그것이 이 서버 안에 있고 정본을 들고 있어서다.
    #
    # 설정돼 있으면 `ok` 다. 계약 enum 이 ok·fail·unconfigured 셋뿐이고 `fail` 은
    # 찔러 보고 실패했을 때인데 여기서는 찌르지 않는다. `configured` 로 내보내면
    # 계약 밖 값이라 화면·감시가 모르는 상태가 된다 (2026-09-02 실측으로 드러남 —
    # 설정이 없는 테스트 환경에서만 통과하고 배포에서 어기는 모양이었다)
    checks = {
        "db": "ok" if runtime.event_store.healthy() else "fail",
        "stt": "ok" if runtime.stt is not None else "unconfigured",
        "llm": "ok" if settings.llm_model or settings.answer_llm_model else "unconfigured",
    }
    # 계약의 embedding 은 ok·fail 둘뿐이라 "예열 중" 을 담을 자리가 없다. 준비되기
    # 전에 상담을 열면 그 요청이 모델 로딩을 통째로 기다리므로, 그 구간은 degraded
    # 로 알리는 편이 사실에 맞다. 임베딩을 아예 안 쓰는 배포는 키를 넣지 않는다
    if settings.embedding_model:
        checks["embedding"] = "ok" if runtime.warmup.ready else "fail"
    return {
        "status": "ok" if "fail" not in checks.values() else "degraded",
        "version": request.app.state.settings.version,
        "checks": checks,
    }
