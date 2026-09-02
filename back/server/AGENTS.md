# back/server — M1 gateway (노순혁)

FastAPI. REST(`contracts/api.openapi.yaml`) · WebSocket(`contracts/ws_protocol.schema.json`) · STT 어댑터와 실행 모드 4종(live·replay·text·trace) · 이벤트 봉투와 append-only 저장 · 이벤트→화면 메시지 변환 · 엔진 호출.

## 허용 import

`engine`(`engine_contract.Engine` 표면만), `contracts`. `rulepack`은 금지.

## 규칙

- **판정을 만드는 흐름의 진입점은 `services/session/pipeline.py`의 `submit_utterance` 하나다.** live·replay·text 가 여기로 합류하고, 이후 `judge → apply → map → persist → publish` 순서를 지킨다. 두 갈래만 여기를 안 지나며 둘 다 판정을 새로 만들지 않는다 — `trace`는 저장된 이벤트를 `replay.py`가 다시 흘릴 뿐이고, `mark_met`·`mark_waived`·`acknowledge`는 엔진을 부르지 않는 사람 결정이다(`ws/handlers/human.py`).
- 이벤트 봉투(`event_id`·`seq_in_session`·`occurred_at`·`session_id`·`pack_version`·`supersedes`)는 server가 찍는다. engine은 payload만 만든다. `supersedes`는 항목별 최신 event_id를 registry가 보관해 채운다.
- server에는 assist 구현이 없다. answer·rephrase·briefing·documents·fold는 engine 소유이며 server는 호출·변환만 한다.
- **REST 는 계약이 정의한 상태 코드 밖으로 나가지 않는다.** 나가야만 하는 자리는 `tests/server/test_contract_status_codes.py` 의 `BEYOND_CONTRACT` 에 이유를 적어야 통과한다. 그 목록이 곧 계약에 추가할 것들이고, 조용히 하나 더 느는 것을 기계가 막는다.
- **후보(`/documents/{id}/candidates`)는 저장하지 않는다.** M3 의 `config/candidate_rules.json` 을 읽어 매번 다시 뜨는 파생물이고, 근거 대조는 `contracts/find_span.py` 로 한다(다른 구현을 쓰면 M3 와 판정이 갈린다). 저장하는 것은 사람이 누른 승인뿐이다(`candidate_approvals`). 그 파일은 import 가 아니라 **경로 의존**이라 M3 가 옮기면 조용히 빈 목록이 된다 — `tests/server/test_candidates.py` 가 먼저 깨지게 해 뒀다.
- STT 조립(`services/stt/assembler.py`)은 프레임 조립·partial/final·문장 분리·PII 마스킹만. 의미 교정은 하지 않는다(교정은 engine judge/refine).
- ws 메시지를 그대로 저장하지 않고, 이벤트를 그대로 전송하지 않는다. 변환은 `mapping/`.
- 회원·인증은 MVP 밖. 다만 **계약이 쓰기 경로에만 토큰을 요구한다**(`securitySchemes.bearerAuth`: 문서 업로드·후보 승인·팩 발행). `settings.admin_token` 하나로 관리하고, 설정이 없으면 그 경로들은 401 이다 — 열어 두면 배포에서 누구나 팩을 발행하고 팩은 불변이라 되돌릴 수 없다. 조회·세션 시작은 열려 있어야 한다(심사위원이 로그인 없이 시연).
- `generated/`는 수동 편집 금지.

## 목표 구조

`DESIGN.md`(워크벤치) 2절. 파일이 생길 때 그 자리에 만든다. 빈 모듈을 미리 만들지 않는다.

그 문서가 아직 레포에 없어, 지금 서 있는 모양을 적어 둔다. 어긋나면 `DESIGN.md` 가 정본이다.

```
bootstrap/    settings · startup(어댑터 조립)
database/     entities · migrations · session
routers/      health · sessions · packs · evidence
mapping/      event_to_s2c · payload_to_event      ← ws↔이벤트 변환은 여기만
services/
  event/      envelope · store
  session/    registry · pipeline · refiner · replay · projection · chains
  stt/        base(Protocol) · deepgram · assembler · session
  documents · candidates · approval_store · report · pack_source · pack_store
ws/           endpoint · connection · protocol · handlers/(human · assist)
```

**실물 어댑터를 늘리면 `tests/server/conftest.py` 의 `_no_live_adapters` 에도 더한다.**
안 그러면 서버 테스트가 외부 API 를 부르고, CI 는 키가 없어 그냥 통과해 키를 가진
사람 PC 에서만 깨진다. `tests/server/test_no_live_adapters.py` 가 그것을 잡는다.
