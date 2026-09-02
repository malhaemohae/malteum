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
import urllib.error
import urllib.request
import uuid
from functools import cache
from pathlib import Path
from urllib.parse import quote

# 한국어 Windows 는 stdout 이 cp949 라 한글·기호가 깨진다. 스크립트가 스스로 UTF-8 을 쓴다
sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8000/api"
WS = "ws://localhost:8000/ws"
SID = "FIXT-SESS-0A"
# 후보가 붙어 있는 원천. M3 config/candidate_rules.json 의 doc_id 와 같다
DOC = "05_상품설명서_정기예금"
AUDIO = Path(__file__).resolve().parent / "stt_audio"
ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    mark = "  OK  " if cond else " FAIL "
    if cond:
        ok += 1
    else:
        fail += 1
    print(f"[{mark}] {label}" + (f"   {detail}" if detail else ""))


CONTRACT = Path(__file__).resolve().parent.parent / "contracts" / "api.openapi.yaml"
violations = []
_checked = set()


@cache
def _spec():
    import yaml

    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _schema(template, status="200"):
    """계약이 그 경로 그 상태에 정한 응답 스키마. `components` 를 얹어 $ref 를 푼다."""
    spec = _spec()
    got = spec["paths"][template]["get"]["responses"][str(status)]
    body = (got.get("content") or {}).get("application/json")
    return {**body["schema"], "components": spec["components"]} if body else None


def contract(template, body, status=200):
    """**배포가 계약대로 답하는가.**

    pytest 는 TestClient 로 본다 — 메모리 저장소에 실물 어댑터가 없는 상태다. 그래서
    설정이 붙어야만 드러나는 어긋남을 못 잡는다(실제로 /health 가 STT·LLM 이 붙은
    배포에서만 계약 밖 값을 냈다). 여기는 컨테이너가 진짜로 답한 것을 본다.
    """
    from jsonschema import Draft202012Validator

    schema = _schema(template, status)
    if schema is None:
        return
    _checked.add(template)
    for e in Draft202012Validator(schema).iter_errors(body):
        violations.append(f"{template} /{'/'.join(map(str, e.path))}: {e.message[:70]}")


def get(path, raw=False, template=None):
    # doc_id 가 한글이라 그대로 넣으면 urllib 이 ascii 로 못 넘긴다. 서버도 근거 URL 을
    # 낼 때 같은 처리를 한다(routers/evidence.py 의 quote). `/` 와 질의문자는 살린다
    with urllib.request.urlopen(BASE + quote(path, safe="/?=&"), timeout=20) as r:
        if raw:
            return r.status, r.read()
        body = json.load(r)
    if template:
        contract(template, body, r.status)
    return r.status, body


def post_status(path, body):
    """상태 코드만 본다. 4xx 는 예외로 올라오므로 여기서 받아 넘긴다."""
    req = urllib.request.Request(
        BASE + quote(path, safe="/?=&"),
        json.dumps(body).encode(),
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def post(path, body):
    req = urllib.request.Request(
        BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.load(r)


def rest():
    print("\n== REST ==")
    s, d = get("/health", template="/health")
    check("health", d["checks"]["db"] == "ok", f"status={d['status']} db={d['checks']['db']}")

    s, d = get("/packs", template="/packs")
    check("packs 목록", len(d["packs"]) >= 1, f"{len(d['packs'])}건")
    ver = d["packs"][0]["pack_version"]

    s, d = get(f"/packs/{ver}", template="/packs/{pack_version}")
    check("packs 상세 = 팩 원문", "items" in d and "sources" in d, f"{ver} 항목 {len(d['items'])}")

    s, d = get("/presets", template="/presets")
    check("presets", "presets" in d, f"{len(d['presets'])}건 (자산 없으면 0 이 정상)")

    s, d = get("/sessions?limit=5", template="/sessions")
    check("sessions 목록", "sessions" in d, f"{len(d['sessions'])}건")

    s, ev = get(f"/sessions/{SID}/events", template="/sessions/{session_id}/events")
    events = ev["events"]
    check("이벤트 원본", len(events) == 31, f"{len(events)}건")
    ref = next(
        e["event_id"] for e in events if e["kind"] == "verdict" and e["verdict"].get("evidence")
    )
    # 기대값을 픽스처에서 뽑는다. 숫자를 박으면 팩이 재발행될 때마다 이 줄만 고치게 되고
    # 무엇이 왜 달라졌는지가 안 남는다 (2026-08-31, 팩 재발행에서 항목 코드 3건 변경)
    superseded = {e["supersedes"] for e in events if e.get("supersedes")}
    live = [
        e["verdict"] for e in events if e["kind"] == "verdict" and e["event_id"] not in superseded
    ]
    want_violated = sum(1 for v in live if v["state"] == "violated")

    s, d = get(f"/sessions/{SID}", template="/sessions/{session_id}")
    check(
        "세션 상세(이벤트를 접은 것)",
        d["status"] == "ended" and d["violations"] == want_violated,
        f"위반 {d['violations']} (픽스처 {want_violated}) · 항목 {len(d['items'])}",
    )
    # 같은 응답 안에서 요약(engine.summarize)과 항목 목록(engine.fold)이 어긋나면
    # 화면은 체크리스트와 진척도가 다른 말을 하는 것을 그대로 그린다
    listed_met = sum(1 for i in d["items"] if i["state"] == "met")
    check(
        "요약 숫자 = 항목 목록",
        d["met"] == listed_met,
        f"summary met {d['met']} · 목록 met {listed_met} · items_total {d['items_total']}",
    )

    s, d = get(f"/sessions/{SID}/report", template="/sessions/{session_id}/report")
    sec = d["sections"]
    check(
        "리포트 (기획 10.1 5단계)",
        sec["summary"]["partial"] == 1 and sec["summary"]["violations"] == 1,
        f"partial {sec['summary']['partial']} · violations {sec['summary']['violations']} · "
        f"위험신호 {len(sec['risk_signals'])} · 타임라인 {len(sec['timeline'])}",
    )
    check("리포트 출처 표기", len(d["sources"]) > 0, f"{len(d['sources'])}건")

    try:
        s, d = get(f"/evidence/{ref}", template="/evidence/{evidence_ref}")
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

    candidates()

    # 배포가 계약대로 답하는가. pytest 는 TestClient 로 보므로 실물 어댑터·postgres 가
    # 붙어야만 드러나는 어긋남을 못 잡는다 (/health 가 실제로 그랬다)
    check(
        "계약 응답 모양 (전 경로)",
        not violations,
        "\n           ".join(violations) if violations else f"{len(_checked)}경로 전부 일치",
    )


def candidates():
    """S4 검수 화면의 입력 (기획 8.2). 심화 경로라 기본 시연에는 안 나오지만
    "자동 폐기 행 노출" 이 P4 의 시각 증거라 여기서 실물로 확인한다."""
    s, d = get(f"/documents/{DOC}/candidates", template="/documents/{doc_id}/candidates")
    cands = d["candidates"]
    verified = [c for c in cands if c["span_verified"]]
    rejected = [c for c in cands if not c["span_verified"]]
    check(
        "후보 목록",
        len(cands) > 0,
        f"{len(cands)}건 · 검증 {len(verified)} · 자동폐기 {len(rejected)}",
    )
    # 걸러서 보내면 화면이 P4 의 증거를 못 보여준다
    check(
        "자동 폐기 행 노출 (P4 시각 증거)",
        len(rejected) > 0 and all(c["status"] == "rejected" for c in rejected),
        " · ".join(c["suggested_code"] for c in rejected) or "없음",
    )
    check(
        "좌표 부여 (형광펜 배경)",
        all(len(c["evidence"].get("bbox", [])) == 4 for c in verified),
        f"{len(verified)}건 bbox",
    )
    # 위험 신호(기획 7.1 ⑦)가 검수 화면까지 오는지. 계약 후보 type 이 3종이던 동안
    # DEP-RSK-001 이 목록에서 통째로 빠졌고, 승인할 방법이 없으면 팩에도 못 들어간다
    check(
        "위험 신호 후보 노출 (기획 7.1 ⑦)",
        any(c["type"] == "risk" for c in cands) or DOC != "03_예금거래기본약관",
        " · ".join(c["suggested_code"] for c in cands if c["type"] == "risk") or "이 문서엔 없음",
    )

    # 승인은 쓰기 경로라 토큰이 필요하다(계약 securitySchemes)
    target = rejected[0] if rejected else None
    if target:
        st = post_status(
            f"/documents/{DOC}/candidates/{target['candidate_id']}/approve",
            {"approved_by": "smoke"},
        )
        check("토큰 없는 승인 거절", st == 401, f"{st} (계약: 401)")


async def ws_human():
    import websockets

    print("\n== WebSocket · 사람 결정 (STT 없이 도는 3층 폴백) ==")
    # 매번 새 세션을 쓴다. 고정 id 를 재사용하면 실행할 때마다 판정이 쌓여 ver 이 계속
    # 오르고, 되돌리기가 "앞선 판정"으로 가는 곳이 지난 실행의 결과가 된다
    sid = f"SMOKE-{uuid.uuid4().hex[:12].upper()}"
    async with websockets.connect(WS) as sock:
        await sock.send(json.dumps({"t": "hello", "mode": "text", "session_id": sid}))
        ready = json.loads(await sock.recv())
        check("hello → ready", ready["t"] == "ready", f"{sid} · 항목 {len(ready['items'])}개")
        item = ready["items"][0]
        code, before = item["item_code"], item["state"]

        async def send(msg, n):
            await sock.send(json.dumps(msg))
            return [json.loads(await sock.recv()) for _ in range(n)]

        got = await send({"t": "mark_met", "item_code": code}, 2)
        check("mark_met", got[0]["state"] == "met", f"{code} → met (ver {got[0]['ver']})")
        # 되돌리기는 앞선 판정으로 간다. 앞선 것이 없으면 출발 상태(unmet)다
        got = await send({"t": "mark_met", "item_code": code, "undo": True}, 2)
        check("mark_met undo", got[0]["state"] == before, f"{before} 로 되돌림")
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


async def ws_live():
    """기획 10.2 심화 경로의 「마이크 직접 발화」. 오디오 → STT → 판정 전 구간.

    서버에 STT 가 없으면 건너뛴다 — 키 없이 도는 기본 경로를 막지 않기 위해서다.
    음원은 `scripts/stt_check.py --make-audio` 가 만든 것을 그대로 쓴다.
    """
    import wave

    import websockets

    print("\n== WebSocket · live (마이크 경로) ==")
    _, h = get("/health", template="/health")
    if h["checks"]["stt"] != "configured":
        print("[ 건너뜀 ] 서버에 STT 가 설정되지 않음 (APP_STT_API_KEY)")
        return
    wav = AUDIO / "deposit_3.wav"
    if not wav.exists():
        print("[ 건너뜀 ] 음원 없음 — scripts/stt_check.py --make-audio 로 만드세요")
        return

    with wave.open(str(wav), "rb") as w:
        pcm, rate = w.readframes(w.getnframes()), w.getframerate()
    chunk = rate * 2 * 100 // 1000  # 계약 audioFrame 100ms

    async with websockets.connect(WS, ping_timeout=120) as sock:
        await sock.send(json.dumps({"t": "hello", "mode": "live"}))
        ready = json.loads(await sock.recv())
        check("hello → ready (live)", ready["t"] == "ready")

        got: list[dict] = []

        async def send():
            for i, off in enumerate(range(0, len(pcm), chunk)):
                await sock.send(i.to_bytes(4, "big") + pcm[off : off + chunk])
                await asyncio.sleep(0.1)  # 실시간 속도

        async def recv():
            end = asyncio.get_running_loop().time() + len(pcm) / (rate * 2) + 8
            while asyncio.get_running_loop().time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(sock.recv(), timeout=5))
                except TimeoutError:
                    continue
                if m["t"] != "ping":
                    got.append(m)

        await asyncio.gather(send(), recv())

    partials = [m for m in got if m["t"] == "partial"]
    utterances = [m for m in got if m["t"] == "utterance"]
    check("partial (중간 전사)", len(partials) > 0, f"{len(partials)}건")
    check(
        "utterance (확정 발화)",
        len(utterances) > 0,
        " / ".join(m["text"][:40] for m in utterances) or "없음",
    )
    verdicts = [m for m in got if m["t"] == "verdict"]
    if verdicts:
        check("판정까지 도달", True, " · ".join(f"{m['item_code']} {m['state']}" for m in verdicts))


def main():
    try:
        rest()
        asyncio.run(ws_human())
        asyncio.run(ws_trace())
        asyncio.run(ws_live())
    except Exception as e:
        print(f"\n[ 중단 ] {type(e).__name__}: {e}")
        return 1
    print(f"\n{'=' * 46}\n통과 {ok} · 실패 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
