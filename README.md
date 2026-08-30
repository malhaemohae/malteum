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

## 재오