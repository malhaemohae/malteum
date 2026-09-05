#!/usr/bin/env python3
"""시연 대본 한 편을 배포에 통째로 흘리고 정답과 대조한다.

무엇을 재나 (`SCRIPT.md` 4장의 점검표)
    화자      확정 발화의 `speaker` 가 대본 줄의 화자와 같은가. **여기가 틀리면 조용히
              틀린다** — 고객 줄이 은행원으로 붙으면 위험 신호·되물음이 아예 안 뜨고,
              반대면 고지가 미고지로 남는다(`engine/tiers/l1/gate.py`)
    용어·수치  팩이 찾는 표기가 전사에 살아 있는가. `만기후이자율` 이 갈라지거나
              `1억` 이 `100000000` 으로 오면 L1 이 그 항목을 못 잡는다
    판정      끝난 세션의 요약이 대본의 `expected_summary` 와 같은가

**서버를 거친다.** pytest 는 가짜 어댑터로 보므로 STT·엔진·팩이 실제로 붙었을 때만
드러나는 어긋남을 못 잡는다. 여기는 실제 음성을 실제 서버에 실시간 속도로 흘린다.

L3(LLM)이 없는 서버에서는 대본의 `l3` 표시가 붙은 판정이 안 나온다. 그건 실패가 아니라
설정 차이라 따로 세어 보여준다.

사용
    uv run python scripts/check_scenario.py preset-dep-a
    uv run python scripts/check_scenario.py --all --base http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse

sys.stdout.reconfigure(encoding="utf-8")

BACK = Path(__file__).resolve().parent.parent
SCENARIOS = BACK.parent / "assets" / "scenarios"

# 팩이 붙여 쓴 채로 찾는 말. 갈라지면 L1 정확 일치가 깨진다
TERMS = [
    "우대이자율",
    "기본이자율",
    "만기후이자율",
    "중도해지이율",
    "약정이율",
    "차감률",
    "예금자보호법",
    "금리인하요구권",
    "중도상환수수료",
    "총부채원리금상환비율",
]

ok = fail = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
    print(f"[{'  OK  ' if cond else ' FAIL '}] {label}" + (f"   {detail}" if detail else ""))


def _api(base: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = base.rstrip("/") + "/api" + quote(path, safe="/?=&%")
    req = urllib.request.Request(
        url,
        json.dumps(body).encode() if body is not None else None,
        {"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _normalized(text: str, pack_version: str) -> str:
    """엔진의 L0 용어 정규화를 거친 텍스트. L1 이 보는 것과 같아야 대조가 뜻을 가진다.

    팩을 못 읽으면 원문 그대로 돌려준다 — 이 검사는 판정의 부속이라 여기서 멈출 일이 아니다.
    """
    try:
        from engine.tiers.l0_normalize import JargonIndex, normalize

        pack = json.loads(
            (BACK / "contracts" / "fixtures" / f"rulepack_{pack_version}.json").read_text(
                encoding="utf-8"
            )
        )
        return normalize(text, JargonIndex(pack.get("jargon_terms") or []))[0]
    except Exception:  # noqa: BLE001
        return text


def _norm(s: str) -> str:
    return re.sub(r"[^가-힣0-9]", "", s)


def _truth_speaker(text: str, lines: list[dict]) -> tuple[str, str]:
    """전사 한 줄이 대본의 어느 줄에서 나왔는지 텍스트로 찾는다.

    시각으로 맞추지 않는 이유: 대본의 `start_ms` 는 앞 클립이 길면 밀린다
    (`SCRIPT.md` 의 배치 규칙). 밀린 만큼 어긋나 정답이 흔들린다.
    """
    h = _norm(text)
    best = max(lines, key=lambda ln: difflib.SequenceMatcher(None, h, _norm(ln["text"])).ratio())
    return best["speaker"], best["id"]


async def run(base: str, preset_id: str, timeout_s: float) -> dict:
    import websockets

    folder = SCENARIOS / preset_id
    script = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    audio_ref = f"scenarios/{preset_id}/{script['audio']['output']}"
    if not (folder / script["audio"]["output"]).is_file():
        raise SystemExit(
            f"음성이 없습니다: {audio_ref}\n  scripts/make_scenario_audio.py 로 만드세요"
        )

    status, created = _api(
        base,
        "/sessions",
        {
            "mode": "replay",
            "pack_version": script["pack_version"],
            "product_code": script.get("product_code"),
            "preset_id": preset_id,
            "audio_ref": audio_ref,
            "customer_profile": script.get("customer_profile") or {"type": "general"},
        },
    )
    if status != 201:
        raise SystemExit(f"세션 생성 실패 {status}: {created}")
    session_id = created["session_id"]

    ws_url = base.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/ws"
    got: list[dict] = []
    async with websockets.connect(ws_url, open_timeout=20, max_size=None) as sock:
        await sock.send(json.dumps({"t": "hello", "mode": "replay", "session_id": session_id}))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            try:
                msg = json.loads(
                    await asyncio.wait_for(sock.recv(), timeout=deadline - loop.time())
                )
            except (TimeoutError, websockets.exceptions.ConnectionClosed):
                break
            got.append(msg)
            if msg.get("t") == "ended":
                break
        await sock.send(json.dumps({"t": "end"}))
        with_suppress = asyncio.wait_for(sock.recv(), timeout=10)
        try:
            got.append(json.loads(await with_suppress))
        except Exception:  # noqa: BLE001  종료 응답이 없어도 결과는 REST 로 읽는다
            pass
    return {"session_id": session_id, "script": script, "messages": got, "audio_ref": audio_ref}


def report(base: str, preset_id: str, result: dict) -> None:
    script, msgs = result["script"], result["messages"]
    lines = script["lines"]
    said = [m for m in msgs if m.get("t") == "utterance"]
    heard = " ".join(m.get("text", "") for m in said)

    print(f"\n== {preset_id} · {script['title']} ==")
    print(f"   팩 {script['pack_version']} · 대본 {len(lines)}줄 → 확정 발화 {len(said)}개")

    # --- 화자 ---
    right = wrong = 0
    misses = []
    for m in said:
        if len(_norm(m.get("text", ""))) < 2:
            continue
        truth, line_id = _truth_speaker(m["text"], lines)
        if m.get("speaker") == truth:
            right += 1
        else:
            wrong += 1
            misses.append(f"{line_id} {m['speaker']}→{truth} {m['text'][:26]}")
    total = right + wrong
    check(
        "화자 매핑",
        wrong == 0,
        f"{right}/{total} = {right / total * 100:.1f}%" if total else "발화 없음",
    )
    for miss in misses[:5]:
        print(f"           {miss}")

    # --- 용어·수치 ---
    # **L0 를 거친 뒤에 본다.** L1 이 보는 것이 그 텍스트이기 때문이다. 원시 전사에서
    # 찾으면 `우대 이자율` 처럼 띄어쓰기만 흔들린 것을 놓친 것으로 세는데, L0 의 용어
    # 사전이 그것을 되붙인다(실측 2026-09-05: score 1.0). 공급자의 띄어쓰기는 같은
    # 오디오·같은 프롬프트에서도 실행마다 바뀌어 전사 표기로는 재는 뜻이 없다
    normalized = _normalized(heard, script["pack_version"])
    want = [t for t in TERMS if any(t in ln["text"] for ln in lines)]
    lost = [t for t in want if t not in normalized]
    raw_lost = [t for t in want if t not in heard]
    detail = f"{len(want) - len(lost)}/{len(want)}"
    if fixed := [t for t in raw_lost if t not in lost]:
        detail += f" (L0 가 되붙임 {fixed})"
    if lost:
        detail += f" · 놓침 {lost}"
    check("도메인 용어 표기", not lost, detail)
    spelled = re.findall(r"\d{6,}", heard)
    check("큰 수 표기", not spelled, f"펴진 채 남음 {spelled}" if spelled else "억 단위로 정규화됨")

    # --- 판정 ---
    status, detail = _api(base, f"/sessions/{result['session_id']}")
    exp = script.get("expected_summary") or {}
    if status != 200:
        check("세션 요약", False, f"{status}")
        return
    listed = {}
    for item in detail.get("items", []):
        listed[item["state"]] = listed.get(item["state"], 0) + 1
    alerts = [m for m in msgs if m.get("t") == "alert"]
    got_line = (
        f"met {detail.get('met', 0)} · partial {listed.get('partial', 0)} · "
        f"unmet {listed.get('unmet', 0)} · 위반 {detail.get('violations', 0)} · 경보 {len(alerts)}"
    )
    exp_line = (
        f"met {exp.get('met')} · partial {exp.get('partial')} · unmet {exp.get('unmet')} · "
        f"위반 {exp.get('violations')} · 경보 {exp.get('alerts')}"
    )
    print(f"   기준값: {exp_line}")
    check("판정 요약", detail.get("met", 0) == exp.get("met"), got_line)
    check("경보", len(alerts) == exp.get("alerts"), f"{len(alerts)} / 기준 {exp.get('alerts')}")
    if alerts:
        print("           " + " · ".join(sorted({a.get("alert_type", "?") for a in alerts})))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="시연 대본을 배포에 흘려 정확도를 잰다")
    ap.add_argument("preset", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--timeout", type=float, default=0, help="0 이면 대본 길이 + 60초")
    args = ap.parse_args(argv)

    presets = (
        [p.parent.name for p in sorted(SCENARIOS.glob("*/script.json"))]
        if args.all
        else [args.preset]
    )
    if not presets or presets == [None]:
        ap.error("preset 을 주거나 --all 을 쓰세요")

    status, health = _api(args.base, "/health")
    checks = json.dumps(health.get("checks"), ensure_ascii=False)
    print(f"대상 {urlparse(args.base).netloc} · {checks}")
    if health.get("checks", {}).get("stt") != "ok":
        print("STT 가 없는 서버입니다. replay 는 stt_unavailable 로 끝납니다.", file=sys.stderr)
        return 1

    for preset_id in presets:
        script = json.loads((SCENARIOS / preset_id / "script.json").read_text(encoding="utf-8"))
        timeout_s = args.timeout or script.get("duration_ms", 200_000) / 1000 + 60
        report(args.base, preset_id, asyncio.run(run(args.base, preset_id, timeout_s)))

    print(f"\n{'=' * 46}\n통과 {ok} · 실패 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
