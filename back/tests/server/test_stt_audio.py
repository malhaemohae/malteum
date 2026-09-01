"""replay 가 읽을 오디오 찾기. `audio_ref` 는 화면에서 오는 값이라 경계를 지켜야 한다."""

import wave

import pytest

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


def test_refuses_to_escape_the_assets_folder(tmp_path):
    """`..` 로 밖을 파고들면 서버의 아무 파일이나 읽힌다."""
    outside = tmp_path.parent / "secret.wav"
    _wav(outside)
    with pytest.raises(AudioNotFound, match="자산 폴더 밖"):
        resolve(tmp_path, f"../{outside.name}")


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
