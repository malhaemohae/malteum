"""replay 가 읽을 오디오 찾기. `audio_ref` 는 화면에서 오는 값이라 경계를 지켜야 한다."""

import wave

import pytest
from fastapi.testclient import TestClient

from server.services.stt.audio import SAMPLE_RATE, AudioNotFound, read_pcm, resolve


def _wav(path, *, channels=1, width=2, rate=SAMPLE_RATE, frames=1600):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * frames * channels * width)
    return path


def test_resolves_inside_assets(tmp_path):
    (tmp_path / "scenarios").mkdir()
    _wav(tmp_path / "scenarios" / "a.wav")
    assert resolve(tmp_path, "scenarios/a.wav").name == "a.wav"


def test_refuses_to_escape_the_root(tmp_path):
    """`..` 로 밖을 파고들면 서버의 아무 파일이나 읽힌다."""
    outside = tmp_path.parent / "secret.wav"
    _wav(outside)
    with pytest.raises(AudioNotFound):
        resolve(tmp_path, f"../{outside.name}")


def test_looks_in_every_root(tmp_path):
    """시연 자산(assets)과 업로드 두 곳을 본다. 뒤엣것은 쓰기가 필요해 자리가 갈린다."""
    assets, uploads = tmp_path / "assets", tmp_path / "uploads"
    assets.mkdir()
    uploads.mkdir()
    _wav(uploads / "SESS-01.wav")
    assert resolve([assets, uploads], "SESS-01.wav").parent == uploads
    with pytest.raises(AudioNotFound):
        resolve([assets, uploads], "none.wav")


def test_refuses_missing_and_empty(tmp_path):
    with pytest.raises(AudioNotFound):
        resolve(tmp_path, "scenarios/none.wav")
    with pytest.raises(AudioNotFound):
        resolve(tmp_path, "")


def test_rejects_wrong_audio_format(tmp_path):
    """규격이 다르면 STT 가 소리를 어긋나게 해석해 전사가 비거나 밀린다.
    변환은 자산을 만드는 쪽이 할 일이라 여기서 거절한다."""
    ok = _wav(tmp_path / "ok.wav")
    assert len(read_pcm(ok)) > 0

    for name, kw in (
        ("stereo.wav", {"channels": 2}),
        ("rate8k.wav", {"rate": 8000}),
        ("eight_bit.wav", {"width": 1}),
    ):
        bad = _wav(tmp_path / name, **kw)
        with pytest.raises(AudioNotFound, match="16kHz mono PCM16"):
            read_pcm(bad)


def test_broken_upload_is_415_not_500(tmp_path):
    """WAV 가 아닌 파일. `wave` 는 규격 불일치가 아니라 파싱 실패를 내므로 따로 잡는다.

    안 잡으면 업로드가 500 이 되고, 심사위원에게는 "서버가 죽었다" 로 보인다.
    기획 10.2 심화 경로에 심사위원 직접 업로드가 있다.
    """
    from server.bootstrap.settings import Settings
    from server.main import create_app

    settings = Settings(event_store="memory", upload_dir=tmp_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        for name, blob in [
            ("잘린 파일", b"RIFF"),
            ("WAV 가 아님", b"\xff\xfb\x90\x00" + "mp3 처럼 생긴 것".encode()),
            ("빈 파일", b""),
        ]:
            got = client.post(
                "/api/sessions/UPLOAD-TEST-01/audio",
                files={"file": ("a.wav", blob, "audio/wav")},
            )
            assert got.status_code == 415, f"{name}: {got.status_code} — 500 이면 안 된다"
            assert got.json()["code"] == "validation_failed"

    # 못 쓸 파일을 남기지 않는다. 남으면 다음 replay 가 그 파일을 재생한다
    assert not list(tmp_path.glob("*.wav")), "거절한 업로드가 디스크에 남았습니다"
