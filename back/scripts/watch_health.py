#!/usr/bin/env python3
"""배포된 서버가 살아 있는지 밖에서 지켜본다. 죽거나 살아나면 한 번 알린다.

## 왜 필요한가

기획 16장 리스크 5 는 **9/7~9/11 접속 불가를 결격**으로 적었고, 대응책 다섯 중 하나가
"외부 헬스체크 알림" 이다. 나머지 넷 중 자동 재시작은 compose 의 `restart: unless-stopped`
가 맡고 있으나, 그것은 **컨테이너가 죽었을 때**만 듣는다. 호스트가 꺼지거나 회선이
끊기거나 터널이 만료되면 컨테이너는 멀쩡한 채로 밖에서 안 보인다. 그 경우를 알아채는
방법은 밖에서 두드려 보는 것뿐이다.

## 반드시 서버 밖에서 돌린다

**서버와 같은 호스트에서 돌리면 의미가 없다.** 호스트가 죽으면 감시도 같이 죽어서
아무도 모른 채 나흘이 지난다. 노트북·휴대폰·다른 VPS 어디든 서버가 아닌 기계에서
돌린다. 그래서 의존성을 하나도 안 쓴다 — python3 만 있으면 어디서든 뜬다.

## 무엇을 이상으로 보나

계약 `/health` 는 `status` 로 요약하고 `checks` 로 부분 장애를 구분한다.

    접속 불가   응답 없음·타임아웃·200 아님·JSON 아님   → 결격 사유. 즉시 알린다
    부분 장애   status=degraded (checks.db 가 fail)     → 뜨지만 판정·저장이 죽었다
    정상        status=ok

**한 번 실패에 알리지 않는다.** 회선은 순간적으로 끊겼다 붙고, 그때마다 알리면 알림을
믿지 않게 된다. `--fails` 번 연속 실패해야 알린다(기본 3회 = 기본 간격에서 약 90초).

**상태가 바뀔 때만 알린다.** 죽은 동안 30초마다 같은 말을 보내면 알림이 소음이 되고,
정작 복구 알림을 못 알아본다. 죽음 → 알림 1회, 복구 → 알림 1회.

## 사용

    python3 scripts/watch_health.py https://<배포주소>
    python3 scripts/watch_health.py https://<배포주소> --once     # cron 용, 1회 검사
    HEALTH_ALERT_WEBHOOK=<URL> python3 scripts/watch_health.py https://<배포주소>

`HEALTH_ALERT_WEBHOOK` 은 JSON `{"text": "..."}` 를 POST 한다. Slack·Discord·ntfy 가
그대로 받는다. 없으면 표준오류로만 적는다 — 터미널을 띄워 두는 것만으로도 감시는 된다.

`--once` 는 종료 코드로 답한다(0 정상 · 1 부분 장애 · 2 접속 불가). cron·uptime 서비스가
그 값을 본다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

# 한국어 Windows 는 stdout 이 cp949 라 한글이 깨진다 (scripts/smoke.py 와 같은 처리)
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

OK, DEGRADED, UNREACHABLE = "정상", "부분 장애", "접속 불가"
EXIT = {OK: 0, DEGRADED: 1, UNREACHABLE: 2}


def probe(base: str, timeout: float) -> tuple[str, str]:
    """(상태, 사람이 읽을 사유). 어떤 예외도 밖으로 내보내지 않는다 — 감시가 죽으면 안 된다."""
    url = base.rstrip("/") + "/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if r.status != 200:
                return UNREACHABLE, f"HTTP {r.status}"
            body = json.load(r)
    except urllib.error.HTTPError as e:
        return UNREACHABLE, f"HTTP {e.code}"
    except Exception as e:  # 타임아웃·DNS·TLS·JSON 전부 여기로 온다
        return UNREACHABLE, f"{type(e).__name__}: {e}"

    checks = body.get("checks") or {}
    if body.get("status") == "ok":
        return OK, f"v{body.get('version', '?')} · " + " ".join(
            f"{k}={v}" for k, v in sorted(checks.items())
        )
    # 계약 status enum 은 ok·degraded 둘. 그 밖의 값이면 서버가 계약을 어긴 것이라 이상으로 본다
    failed = [k for k, v in checks.items() if v == "fail"] or ["(불명)"]
    return DEGRADED, f"status={body.get('status')} · 실패한 검사: {', '.join(failed)}"


def notify(message: str, webhook: str | None) -> None:
    stamp = datetime.now(UTC).astimezone().strftime("%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", file=sys.stderr, flush=True)
    if not webhook:
        return
    try:
        req = urllib.request.Request(
            webhook,
            json.dumps({"text": f"[말틈] {message}"}).encode(),
            {"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as e:
        # 알림 실패로 감시를 멈추지 않는다. 알림이 안 가는 것보다 감시가 죽는 것이 나쁘다
        print(f"[{stamp}] 알림 전송 실패({type(e).__name__}). 감시는 계속한다", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser(description="배포 서버 외부 감시 (기획 16장 리스크 5)")
    p.add_argument("base", help="배포 주소. 예: https://malteum.example.com")
    p.add_argument("--interval", type=float, default=30, help="검사 간격 초 (기본 30)")
    p.add_argument("--timeout", type=float, default=10, help="응답 대기 초 (기본 10)")
    p.add_argument("--fails", type=int, default=3, help="연속 실패 몇 번에 알릴지 (기본 3)")
    p.add_argument("--once", action="store_true", help="1회 검사 후 종료 코드로 답한다")
    args = p.parse_args()

    webhook = os.environ.get("HEALTH_ALERT_WEBHOOK") or None

    if args.once:
        state, why = probe(args.base, args.timeout)
        print(f"{state} · {why}")
        return EXIT[state]

    notify(
        f"감시 시작: {args.base} · {args.interval:g}초 간격 · {args.fails}회 연속 실패 시 알림",
        webhook,
    )
    announced = OK  # 마지막으로 알린 상태. 처음에는 정상으로 두고 나빠질 때 알린다
    streak = 0
    last_why = ""

    while True:
        state, why = probe(args.base, args.timeout)
        if state == OK:
            if announced != OK:
                notify(f"복구됨 — {why}", webhook)
                announced, streak = OK, 0
            else:
                streak = 0
        else:
            # 상태가 바뀌면(부분 장애 → 접속 불가) 연속 횟수를 다시 센다. 다른 사고다
            streak = streak + 1 if why[:20] == last_why[:20] or streak else 1
            if streak >= args.fails and announced != state:
                notify(f"{state} — {why} ({streak}회 연속)", webhook)
                announced = state
        last_why = why
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n감시 중단", file=sys.stderr)
        sys.exit(130)
