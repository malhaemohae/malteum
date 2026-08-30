#!/usr/bin/env python3
"""백엔드 수동 점검. 기획 10.1 의 심사위원 기본 경로를 그대로 훑는다.

17장 QA 범위가 "화면은 10장 심사 경로를 수동 체크리스트로" 이므로, 그 체크리스트의
백엔드 쪽을 사람이 한 번에 돌려볼 수 있게 모아 둔 것이다. pytest 가 아니라 **떠 있는
서버**를 밖에서 두드린다. 컨테이너 배포가 실제로 답하는지는 이렇게만 알 수 있다.

사용:
    docker compose up --build -d          # 레포 루트에서
    uv run python scripts/smoke.py        # back/ 에서
"""

import asyncio
import json
import sys
import urllib.request

# 한국어 Windows 는 stdout 이 cp949 라 한글·기호가 깨진다. 스크립트가 스스로 UTF-8 을 쓴다
sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8000/api"
WS = "ws://localhost:8000/ws"
SID = "FIXT-SESS-0A"
ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    mark = "  OK  " if cond else " FAIL "
    if cond:
        ok += 1
    else:
        fail += 1
    print(f"[{mark}] {label}" + (f"   {detail}" if detail else ""))


def get(path, raw=False):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return (r.status, r.read()) if raw else (r.status, json.load(r))


def post(path, body):
    req = urllib.request.Request(
        BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.load(r)


def rest():
    print("\n== REST ==")
    s, d = get("/health")
    check("health", d["checks"]["db"] == "ok", f"status={d['status']} db={d['checks']['db']}")

    s, d = get("/packs")
    check("packs 목록", len(d["packs"]) >= 1, f"{len(d['packs'])}건")
    ver = d["packs"][0]["pack_version"]

    s, d = get(f"/packs/{ver}")
    check("packs 상세 = 팩 원문", "items" in d and "sources" in d, f"{ver} 항목 {len(d['items'])}")

    s, d = get("/presets")
    check("presets", "presets" in d, f"{len(d['presets'])}건 (자산 없으면 0 이 정상)")

    s, d = get("/sessions?limit=5")
    check("sessions 목록", "sessions" in d, f"{len(d['sessions'])}건")

    s, d = get(f"/sessions/{SID}")
    check(
        "세션 상세(이벤트를 접은 것)",
        d["status"] == "ended" and d["met"] == 4 and d["violations"] == 1,
        f"met {d['met']}/{d['items_total']} · 위반 {d['violations']} · 항목 {len(d['items'])}",
    )

    s, d = get(f"/sessions/{SID}/events")
    check("이벤트 원본", len(d["events"]) == 31, f"{len(d['events'])}건")
    ref = next(
        e["event_id"]
        for e in d["events"]
        if e["kind"] == "verdict" and e["verdict"].get("evidence")
    )

    s, d = get(f"/sessions/{SID}/report")
    sec = d["sections"]
    check(
        "리포트 (기획 10.1 5단계)",
        sec["summary"]["partial"] == 1 and sec["summary"]["violations"] == 1,
        f"partial {sec['summary']['partial']} · violations {sec['summary']['violations']} · "
        f"위험신호 {len(sec['risk_signals'])} · 타임라인 {len(sec['timeline'])}",
    )
    check("리포트 출처 표기", len(d["sources"]) > 0, f"{len(d['sources'])}건")

    try:
        s, d = get(f"/evidence/{ref}")
        check(
            "근거 원문 (기능 14)",
            all(d.get(k) for k in ("doc_id", "page", "span", "page_image_url", "page_size")),
            f"{d['doc_id']} p{d['page']} · {d['span'][:28]}",
        )
        s, png = get(d["page_image_url"].replace("/api", ""), raw=True)
        check("페이지 렌더", png.startswith(bytes([137, 80, 78, 71])), f"{len(png):,} bytes")
    except Exception as e:
        check("근거 원문 (기능 14)", False, f"{type(e).__name__} · 원문 PDF 가 안 보임")
        check("페이지 렌더", False, "compose 에 assets 마운트 필요")


async def ws_human():
    import websockets

    print("\n== WebSocket · 사람 결정 (STT 없이 도는 3층 폴백) ==")
    async with websockets.connect(WS) as sock:
        await sock.send(json.dumps({"t": "hello", "mode": "text", "session_id": "SMOKE-SESS-0001"}))
        ready = json.loads(await sock.recv())
        check("hello → ready", ready["t"] == "ready", f"항목 {len(ready['items'])}개")
        code = ready["items"][0]["item_code"]

        async def send(msg, n):
            await sock.send(json.dumps(msg))
            return [json.loads(await sock.recv()) for _ in range(n)]

        got = await send({"t": "mark_met", "item_code": code}, 2)
        check("mark_met", got[0]["state"] == "met", f"{code} → met (ver {got[0]['ver']})")
        got = await send({"t": "mark_met", "item_code": code, "undo": True}, 2)
        check("mark_met undo", got[0]["state"] == "unmet", f"되돌림 (ver {got[0]['ver']})")
        got = await send({"t": "mark_waived", "item_code": code, "reason": "해당 없음"}, 2)
        check("mark_waived", got[0]["state"] == "waived", f"ver {got[0]['ver']}")
        got = await send({"t": "mark_met", "item_code": "XXX-YYY-999"}, 1)
        check("없는 항목 거절", got[0]["t"] == "error", got[0]["code"])
        got = await send({"t": "end"}, 1)
        check("end", got[0]["t"] == "ended", f"waived {got[0]['summary']['waived']}")


async def ws_trace():
    import websockets

    print("\n== WebSocket · trace 재생 (STT·LLM 미호출) ==")
    s, d = post("/sessions", {"mode": "trace", "source_session_id": SID})
    check("POST /sessions (trace)", s == 201, d["session_id"])
    async with websockets.connect(WS) as sock:
        await sock.send(json.dumps({"t": "hello", "mode": "trace", "session_id": d["session_id"]}))
        ready = json.loads(await sock.recv())
        check("ready", ready["t"] == "ready", f"mode={ready['mode']}")
        got = []
        try:  # 원본 간격대로 흐른다. 앞의 몇 개만 본다
            while len(got) < 3:
                got.append(json.loads(await asyncio.wait_for(sock.recv(), timeout=20)))
        except TimeoutError:
            pass
        check(
            "자동 재생 시작 (별도 시작 메시지 없음)", len(got) > 0, " · ".join(m["t"] for m in got)
        )


def main():
    try:
        rest()
        asyncio.run(ws_human())
        asyncio.run(ws_trace())
    except Exception as e:
        print(f"\n[ 중단 ] {type(e).__name__}: {e}")
        return 1
    print(f"\n{'=' * 46}\n통과 {ok} · 실패 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
