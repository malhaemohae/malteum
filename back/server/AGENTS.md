# back/server — M1 gateway (노순혁)

FastAPI. REST(`contracts/api.openapi.yaml`) · WebSocket(`contracts/ws_protocol.schema.json`) · STT 어댑터와 실행 모드 4종(live·replay·text·trace) · 이벤트 봉투와 append-only 저장 · 이벤트→화면 메시지 변환 · 엔진 호출.

## 허용 import

`engine`(`engine_contract.Engine` 표면만), `contracts`. `rulepack`은 금지.

## 규칙

- 흐름의 진입점은 `services/session/pipeline.py`의 `submit_utterance` 하나다. 네 모드가 모두 여기로 합류하고, 이후 `judge → apply → map → persist → publish` 순서를 지킨다.
- 이벤트 봉투(`event_id`·`seq_in_session`·`occurred_at`·`session_id`·`pack_version`·`supersedes`)는 server가 찍는다. engine은 payload만 만든다. `supersedes`는 항목별 최신 event_id를 registry가 보관해 채운다.
- server에는 assist 구현이 없다. answer·rephrase·briefing·documents·fold는 engine 소유이며 server는 호출·변환만 한다.
- STT 조립(`services/stt/assembler.py`)은 프레임 조립·partial/final·문장 분리·PII 마스킹만. 의미 교정은 하지 않는다(교정은 engine judge/refine).
- ws 메시지를 그대로 저장하지 않고, 이벤트를 그대로 전송하지 않는다. 변환은 `mapping/`.
- 회원·인증은 MVP 밖. `admin_token`은 무시한다.
- `generated/`는 수동 편집 금지.

## 목표 구조

`DESIGN.md`(워크벤치) 2절. 파일이 생길 때 그 자리에 만든다. 빈 모듈을 미리 만들지 않는다.
