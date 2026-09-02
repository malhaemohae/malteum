"""서버 테스트가 외부 API 를 부르지 않는지 지킨다.

**왜 이 테스트가 있나.** `settings` 에 실물 어댑터가 하나 늘 때마다
`tests/server/conftest.py` 의 `_no_live_adapters` 도 함께 늘어야 한다. 그 연결을
아무 문서도 말하지 않고 import-linter 도 못 잡아, 실제로 두 번 빠뜨렸다 —
2026-09-02 STT 어댑터를 붙이면서 서버 테스트가 매번 Deepgram 에 접속했다.

**빠뜨리면 어떻게 되나.** CI 는 키가 없어 그냥 통과하고, 키를 가진 사람 PC 에서만
테스트가 멈춘다. 남의 영역에서 난 실패라 원인을 찾기도 어렵다. 게다가 테스트를
돌릴 때마다 유료 크레딧이 샌다.

conftest 가 지운 것을 여기서 되짚는 꼴이라 얼핏 겹쳐 보이지만, 지우는 쪽과 확인하는
쪽이 갈려 있어야 한 쪽을 빠뜨렸을 때 드러난다.
"""

from server.bootstrap.settings import Settings
from server.bootstrap.startup import build_runtime

FIX = (
    "settings 에 실물 어댑터를 늘렸으면 "
    "tests/server/conftest.py 의 _no_live_adapters 에도 더하세요."
)


def test_runtime_has_no_live_adapter():
    """개발자의 .env 에 키가 있어도 서버 테스트는 네트워크 없이 부팅해야 한다."""
    settings = Settings(event_store="memory")

    # 값을 먼저 bool 로 접는다. 그냥 `assert not settings.stt_api_key` 로 쓰면 pytest 가
    # 실패할 때 Settings 를 통째로 펼쳐 API 키가 터미널·CI 로그에 그대로 찍힌다
    leaked = {
        "APP_STT_API_KEY": bool(settings.stt_api_key),
        "APP_LLM_MODEL": bool(settings.llm_model),
        "APP_EMBEDDING_MODEL": bool(settings.embedding_model),
    }
    assert not any(leaked.values()), f"{[k for k, v in leaked.items() if v]} 가 샜습니다. {FIX}"

    runtime = build_runtime(settings)
    assert runtime.stt is None, f"STT 어댑터가 살아 있습니다. {FIX}"
