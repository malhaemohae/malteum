"""심사용 프리셋 목록. 원천은 R5 가 채우는 `assets/scenarios/<id>/script.json` 이다.

계약이 이 경로를 둔 이유는 "심사위원이 로그인·설정 없이 바로 시연에 들어갈 수 있게 미리
굳혀 둔 조합" 이다. 그래서 **대본 파일 하나가 곧 프리셋 하나**이고, 서버는 그 파일을
계약 `Preset` 모양으로 옮기기만 한다. 목록을 따로 들고 있으면 대본과 어긋난다.

**오디오가 없으면 `audio_ref` 를 넣지 않는다.** 대본과 음성은 둘 다 커밋되지만 들어오는
시점이 다르다. 대본을 먼저 쓰고 음성은 뒤에 TTS 로 뽑으므로 그 사이에는 `script.json` 만
있는 프리셋이 존재한다(실제로 C · D 가 2026-09-06 까지 그 상태였다). 없는데 참조를 주면
화면은 시연 버튼을 켜고 심사위원이 눌렀을 때 재생이 실패한다. 없으면 없다고 말하고,
`description` 에 무엇이 빠졌는지 적어 화면이 그대로 보여줄 수 있게 한다.

이 파일이 파일 존재로 판단하므로 **프런트도 같은 기준을 써야 한다.** 프런트가 프리셋 이름을
따로 적어 두었다가 여기서 광고한 프리셋을 못 재생한 적이 있다(2026-09-06,
`front/scripts/prepare-replay-audio.cjs` 가 이제 같은 폴더를 훑는다).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCENARIOS = "scenarios"  # assets_dir 아래. audio_ref 도 이 뿌리 기준이다(stt/audio.resolve)

# 대본의 `expect` 에 적힌 기계 표기 → 심사위원이 읽을 말.
# 계약: expected_highlights 는 "심사위원이 무엇을 볼지 미리 알 수 있게" 하는 값이다
LABEL = {
    "number_mismatch": "숫자 오류 경보",
    "forbidden_phrase": "금지 발언 경보",
    "risk_signal": "위험 신호 경보",
    "rephrase": "쉬운 말 재진술 카드",
    "nudge": "미고지 넛지",
}


def _highlights(script: dict[str, Any]) -> list[str]:
    summary = script.get("expected_summary") or {}
    out: list[str] = []
    if summary.get("items_total"):
        out.append(
            f"필수 항목 {summary['items_total']}개 · 고지 {summary.get('met', 0)}"
            f" · 부분 고지 {summary.get('partial', 0)} · 미고지 {summary.get('unmet', 0)}"
        )
    if summary.get("violations"):
        out.append(f"금지 발언 위반 {summary['violations']}건")

    # 대본에 실제로 적힌 것만 센다. 없는 장면을 "보일 예정" 이라고 적으면 안 된다
    counts: dict[str, int] = {}
    for line in script.get("lines", []):
        for item in line.get("expect", []):
            parts = item.split()
            if len(parts) < 2 or parts[0] not in ("alert", "assist"):
                continue
            label = LABEL.get(parts[1])
            if label:
                counts[label] = counts.get(label, 0) + 1
    out += [f"{label} {n}건" for label, n in counts.items()]
    return out


def _one(script_path: Path, assets_dir: Path) -> dict[str, Any] | None:
    try:
        script = json.loads(script_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # 대본 하나가 깨져도 목록 전체를 막지 않는다
    preset_id = script.get("preset_id") or script_path.parent.name
    for required in ("mode", "product_code", "pack_version"):
        if not script.get(required):
            return None  # 계약 required 를 못 채우면 내보내지 않는다

    preset: dict[str, Any] = {
        "preset_id": preset_id,
        "label": script.get("title") or preset_id,
        "mode": script["mode"],
        "product_code": script["product_code"],
        "pack_version": script["pack_version"],
    }
    if profile := script.get("customer_profile"):
        preset["customer_profile"] = profile
    if highlights := _highlights(script):
        preset["expected_highlights"] = highlights

    ref = f"{SCENARIOS}/{script_path.parent.name}/{(script.get('audio') or {}).get('output')}"
    note = _duration(script)
    if (assets_dir / ref).is_file():
        preset["audio_ref"] = ref
    else:
        note = f"{note} · 음성 파일이 아직 없어 재생할 수 없습니다({ref})".lstrip(" ·")
    if note:
        preset["description"] = note
    return preset


def _duration(script: dict[str, Any]) -> str:
    ms = script.get("duration_ms")
    if not isinstance(ms, int) or ms <= 0:
        return ""
    return f"{ms // 60000}분 {ms % 60000 // 1000}초"


def load(assets_dir: Path) -> list[dict[str, Any]]:
    """`assets/scenarios/*/script.json` → 계약 `Preset` 목록. 없으면 빈 목록."""
    root = assets_dir / SCENARIOS
    if not root.is_dir():
        return []
    found = [_one(p, assets_dir) for p in sorted(root.glob("*/script.json"))]
    return [p for p in found if p is not None]
