"""심사용 프리셋 (`GET /presets`).

계약이 이 경로를 둔 이유가 "심사위원이 로그인·설정 없이 바로 시연" 이라, 여기서 틀리면
심사 첫 화면이 틀린다. 두 가지를 못박는다 — **계약 `Preset` 모양을 지키는가**, 그리고
**음성이 없을 때 재생할 수 있다고 말하지 않는가**.

뒤엣것이 중요하다. 대본(`script.json`)은 커밋되지만 음성(`audio.wav`)은 R5 가 만들어
각자 두는 파일이라 없을 수 있다. 없는데 `audio_ref` 를 주면 화면이 시연 버튼을 켜고,
심사위원이 누른 뒤에야 재생이 실패한다.
"""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from server.bootstrap.settings import Settings
from server.main import create_app
from server.services import presets
from server.services.stt import audio

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "back" / "contracts"
ASSETS = ROOT / "assets"

SCRIPT = {
    "preset_id": "preset-x",
    "title": "시험용 상담",
    "mode": "replay",
    "product_code": "TEST-001",
    "pack_version": "DEP-2026.08-v6",
    "duration_ms": 90_000,
    "customer_profile": {"type": "general", "tags": ["elderly"]},
    "audio": {"output": "audio.wav"},
    "expected_summary": {"items_total": 3, "met": 2, "partial": 1, "unmet": 0, "violations": 1},
    "lines": [
        {"expect": ["alert number_mismatch warning said=0.5%"]},
        {"expect": ["assist rephrase customer_reask"]},
        {"expect": ["verdict DEP-INT-001 omission met L1"]},
    ],
}


def _write(assets: Path, name: str, script: dict | str, *, audio_bytes: bytes | None = None):
    folder = assets / "scenarios" / name
    folder.mkdir(parents=True, exist_ok=True)
    body = script if isinstance(script, str) else json.dumps(script, ensure_ascii=False)
    (folder / "script.json").write_text(body, encoding="utf-8")
    if audio_bytes is not None:
        (folder / "audio.wav").write_bytes(audio_bytes)
    return folder


def _wav() -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(audio.SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * audio.SAMPLE_RATE)
    return buf.getvalue()


# --- 계약 ------------------------------------------------------------------


def _preset_schema() -> dict:
    spec = yaml.safe_load((CONTRACTS / "api.openapi.yaml").read_text(encoding="utf-8"))
    return {**spec["components"]["schemas"]["Preset"], "components": spec["components"]}


def test_real_scenarios_match_the_contract():
    """레포에 실제로 들어 있는 대본이 계약 모양인지. R5 가 대본을 고치면 여기가 먼저 깬다."""
    loaded = presets.load(ASSETS)
    assert loaded, "assets/scenarios 에 대본이 있어야 한다"
    validator = Draft202012Validator(_preset_schema())
    for preset in loaded:
        errors = [
            f"/{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(preset)
        ]
        assert not errors, f"{preset['preset_id']} — {errors}"


def test_endpoint_serves_them(tmp_path):
    with TestClient(create_app(Settings(event_store="memory"))) as client:
        got = client.get("/api/presets")
    assert got.status_code == 200
    ids = [p["preset_id"] for p in got.json()["presets"]]
    assert "preset-dep-a" in ids, ids


def test_label_and_profile_come_from_the_script(tmp_path):
    _write(tmp_path, "preset-x", SCRIPT)
    (one,) = presets.load(tmp_path)
    assert one["label"] == "시험용 상담"
    assert one["customer_profile"] == {"type": "general", "tags": ["elderly"]}
    assert one["description"].startswith("1분 30초")


# --- 음성 유무 -------------------------------------------------------------


def test_missing_audio_gives_no_audio_ref(tmp_path):
    """없는 음성을 참조로 주면 화면이 못 도는 시연 버튼을 켠다."""
    _write(tmp_path, "preset-x", SCRIPT)
    (one,) = presets.load(tmp_path)
    assert "audio_ref" not in one
    assert "음성 파일이 아직 없어" in one["description"]
    assert "scenarios/preset-x/audio.wav" in one["description"]


def test_audio_ref_is_resolvable_when_the_file_is_there(tmp_path):
    """참조를 줄 때는 replay 가 실제로 그 파일을 찾을 수 있어야 한다."""
    _write(tmp_path, "preset-x", SCRIPT, audio_bytes=_wav())
    (one,) = presets.load(tmp_path)
    assert one["audio_ref"] == "scenarios/preset-x/audio.wav"
    assert "음성 파일이" not in one.get("description", "")
    # stt/audio.resolve 가 쓰는 뿌리와 같은 규약인지 — 여기서 어긋나면 재생만 조용히 실패한다
    assert audio.resolve([tmp_path], one["audio_ref"]).is_file()


# --- 망가진 입력 -----------------------------------------------------------


def test_broken_script_does_not_break_the_list(tmp_path):
    _write(tmp_path, "preset-x", SCRIPT)
    _write(tmp_path, "preset-broken", "{ 깨진")
    assert [p["preset_id"] for p in presets.load(tmp_path)] == ["preset-x"]


@pytest.mark.parametrize("missing", ["mode", "product_code", "pack_version"])
def test_script_without_a_contract_required_field_is_dropped(missing, tmp_path):
    """required 를 못 채운 프리셋을 내보내면 화면이 그 값을 믿고 세션을 연다."""
    _write(tmp_path, "preset-x", {k: v for k, v in SCRIPT.items() if k != missing})
    assert presets.load(tmp_path) == []


def test_no_scenarios_folder_is_an_empty_list(tmp_path):
    assert presets.load(tmp_path) == []


# --- 심사위원이 무엇을 볼지 ------------------------------------------------


def test_highlights_only_name_scenes_the_script_actually_has(tmp_path):
    _write(tmp_path, "preset-x", SCRIPT)
    (one,) = presets.load(tmp_path)
    highlights = one["expected_highlights"]
    assert "필수 항목 3개 · 고지 2 · 부분 고지 1 · 미고지 0" in highlights
    assert "금지 발언 위반 1건" in highlights
    assert "숫자 오류 경보 1건" in highlights
    assert "쉬운 말 재진술 카드 1건" in highlights
    # 대본에 없는 장면은 적지 않는다
    assert not any("위험 신호" in h for h in highlights)
