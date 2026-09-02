# 말틈

금융 AI Challenge 출품작. 은행 창구 상담을 실시간으로 듣고 필수 고지 누락·금지 발언·숫자 오류를 은행원에게 귀띔하는 시스템의 모노레포.

## 모듈 지도

```
.
├── front/            M4 web  (서재오)   Next.js. back/contracts/fixtures/ws_messages.json 으로 서버 없이 화면을 그린다
├── back/             uv 루트. pyproject · ruff · import-linter · Dockerfile · alembic
│   ├── contracts/    계약 정본 (임한빈 작성, 8/28 동결). 네 모듈의 유일한 접점
│   ├── server/       M1 gateway (노순혁)  FastAPI · WebSocket · STT 어댑터 · 이벤트 저장 · 엔진 호출
│   ├── engine/       M2 engine  (허현준)  판정 L1→L2→L3 · assist · 상태 접기. WebSocket·DB 를 모른다
│   ├── rulepack/     M3 rulepack (임한빈) 규정 PDF → 팩 JSON → postgres 적재
│   └── regwatch/     규정 개정 일일 감시 (임한빈). 완전 독립, 표준 라이브러리만
├── db/               init.sql (pgvector 확장)
├── docs/기획/         핵심기획안 (md·PDF) · 현장검증 인터뷰 · 검증 기록 · 와이어프레임. 구현의 컨텍스트
├── assets/           03_규정문서/ (PDF, git 제외) · scenarios/<id>/ (manifest·audio·trace)
└── compose.yaml      postgres16+pgvector · server
```

호출 방향 한 줄:

```
M3 ──rulepack──▶ M2 ◀──engine_contract── M1 ──ws_protocol──▶ M4
                  │                       │                    │
                  └────────events─────────┴──api.openapi───────┘
                                 ▼
                                 DB
```

import 경계는 `back/pyproject.toml`의 import-linter가 강제한다: `server → engine, contracts` / `engine → contracts` / `rulepack → contracts`. 그 밖의 import는 CI에서 실패한다.

## 시작

필요한 것: Python 3.12 · uv · Docker · **JDK 17 이상**.

JDK 는 rulepack 의 구조 추출이 OpenDataLoader(java)를 부르기 때문에 필요하다. 없으면
`make test` 가 rulepack 테스트에서 멈춘다. `pip install install-jdk` 후
`python -c "import jdk; jdk.install('21')"` 로 받으면 된다. CI 는 temurin 21 을 쓴다.

```bash
cd back && uv sync                       # 파이썬 3.12 · 의존성
make test                                # ruff · lint-imports · pytest
cd back && uv run uvicorn server.main:app --reload   # http://localhost:8000/health · ws://localhost:8000/ws
make up                                  # docker compose: postgres + server
```

각 폴더의 `AGENTS.md`가 그 모듈의 담당·허용 import·규칙을 적는다. 사람과 에이전트 모두 그 문서를 먼저 읽는다.

## 배포 유지 (기획 16장 리스크 5 — 접속 불가는 결격)

9/7~9/11 나흘 무중단이 요건이라, 죽는 것보다 **죽은 줄 모르는 것**이 위험하다.

```bash
python3 back/scripts/watch_health.py https://<배포주소>              # 계속 지켜본다
python3 back/scripts/watch_health.py https://<배포주소> --once       # 1회. 종료코드 0·1·2
HEALTH_ALERT_WEBHOOK=<URL> python3 back/scripts/watch_health.py …    # Slack·Discord·ntfy
```

**서버가 아닌 기계에서 돌린다.** 같은 호스트에서 돌리면 호스트가 죽을 때 감시도 같이 죽는다. 의존성이 없어 python3 만 있으면 노트북이든 다른 VPS 든 뜬다.

`restart: unless-stopped`(compose)는 컨테이너가 죽었을 때만 듣는다. **호스트 재부팅까지 덮으려면 도커 데몬이 부팅에 뜨게 해 둔다** — `sudo systemctl enable docker`. 이것을 안 하면 정전 뒤에 아무것도 안 뜬다.

| 리스크 5 대응책 | 상태 |
| --- | --- |
| 자동 재시작 | `restart: unless-stopped` (compose) |
| 부팅 자동 기동 | `systemctl enable docker` 필요 — 호스트에서 한 번 |
| 외부 헬스체크 알림 | `scripts/watch_health.py` |
| VPS 미러 · DNS 전환 | 미정 (기획 19장 R1) |
| UPS · 시연 영상 백업 | R5 |

## 재오