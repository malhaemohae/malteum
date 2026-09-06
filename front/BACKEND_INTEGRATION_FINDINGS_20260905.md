# 실제 음성 통합 검수: 백엔드 수정 2건 중 1건 남음

> **현재 상태(2026-09-07)**: 2절은 해결했다(그 절의 「해결」 참고). 1절은 `back/engine`
> 소관으로 남아 있다. 아래 본문은 2026-09-05 검수 시점의 관측 기록 그대로 둔다.

## 환경과 완료 범위

Docker PostgreSQL 16 + pgvector, 공식 규정 팩 2개/임베딩 58개, CPU Sortformer 화자 분리, 팀 환경의 OpenAI `gpt-4o-transcribe`, OpenRouter `qwen/qwen3-8b`, 로컬 multilingual-e5-small 임베딩을 연결했다. 프론트의 녹음 버튼으로 저장소의 합성 음원을 PCM 업링크하고 실제 외부 전사/LLM·엔진·DB를 사용했다. 제품 코드의 대체 판정이나 카탈로그 fixture 가로채기는 사용하지 않았다.

- 음성 검수 세션: `01M1QW2KBAS59A2WQ7VQ3PTB07`
- 종료 수신 시점: PCM 880프레임, WS 전사 14건, 판정 9건, 금지 표현 경보 1건, DB 이벤트 30건.
- 판정에는 실제 L1/L2/L3가 모두 포함된다. 화자 역할 신뢰도 0.95와 이해 확인 L3 판정도 확인했다.
- 이는 전송/연동 성공이다. 아래 두 승인 조건이 실패했으므로 최종 서비스 검수 완료로 간주하지 않는다.

## 1. 발화가 분리되면 숫자 오류 경보 누락

프론트가 아닌 동일 백엔드 TEXT/WS 경로로 재현:

| 입력 | 실제 결과 |
| --- | --- |
| `받으시는 이자 수익에는 과세가 되는데요, 세율은 14%입니다.` 한 번 전송 | `number_mismatch` 경보 발생 |
| `받으시는 이자 수익에는 과세가 되는데요.` 다음 `세율은 14%입니다.`로 분리 전송 | 숫자 오류 경보 없음 |

실제 음성 전사도 이 두 문장으로 나뉘었고, 화자는 둘 다 teller / 0.95였다. 팩의 15.4%와 다른 14%가 원문에 존재하지만 경보가 누락됐다. 이것은 관측한 입력 조건이며, 엔진 내부의 정확한 원인/수정 위치는 M1/M2 검토가 필요하다. 프론트가 숫자를 바꾸거나 경보를 합성해 보완하지 않는다.

완료 조건: 같은 상담 문맥에서 연속 발화로 분리되어도 실제 수치 대조 경보와 근거 참조가 생성돼야 한다.

## 2. 종료 확인 뒤 잔여 STT 이벤트가 저장됨 (해결)

동일 음성 검수 세션의 영구 이벤트 순서:

| seq_in_session | kind | occurred_at (KST) |
| --- | --- | --- |
| 29 | session_ended | 2026-09-05 13:10:25.174 |
| 30 | utterance | 2026-09-05 13:10:26.821 |
| 31 | utterance | 2026-09-05 13:10:26.838 |
| 32 | utterance | 2026-09-05 13:10:26.851 |

최초 종료 리포트는 30개 이벤트 시점에 조회됐지만 이후 33개가 됐다. 종료 후 브라우저를 닫자 서버 로그에 잔여 전사 전송의 `WebSocketDisconnect`도 발생했다. 현재 프론트는 계약의 `ended`를 받은 뒤 리포트로 이동하므로, 백엔드에서 잔여 전사·예약 판정을 정리한 뒤 `session_ended/ended`를 마지막으로 확정해야 한다.

완료 조건: 마지막 발화의 전사와 필요한 판정이 저장된 후 종료 이벤트/종료 응답이 도착하고, 최초 리포트와 이후 재조회 내용이 동일해야 한다. 프론트에서 임의 시간만 기다리는 방식으로 완료를 가장하지 않는다.

### 해결 (브랜치 `feat/server-stt-flush-order`)

원인은 종료 처리의 순서였다. `back/server/ws/endpoint.py` 의 `end` 가 `session_ended` 를 쓰고 소켓 루프를 빠져나간 뒤에야 `finally` 에서 STT 를 닫는데, 발화 단위 어댑터의 마지막 구간은 그 `aclose()` 에서만 닫힌다(`services/stt/openai_file.py`). 프론트가 flush 를 보내지 않은 것이 원인이 아니다. 계약의 c2s 열 가지에 `flush` 도 `audio_pause` 도 없어 보낼 수단 자체가 없었다(`back/contracts/ws_protocol.schema.json`). 계약은 동결 상태 그대로 두고 서버에서 닫았다.

| 고친 것 | 자리 |
| --- | --- |
| `end` 가 잔여 전사와 예약 보정을 끝낸 뒤 `session_ended` 를 쓴다 | `server/ws/endpoint.py` |
| 예약된 L3 보정을 버리지 않고 마저 돌린다 (`Refiner.drain`) | `server/services/session/refiner.py` |
| 마무리에 상한 `session_finish_budget_s`(15초). 넘겨도 종료는 끝난다 | `server/ws/endpoint.py` |
| `session_ended` 뒤에는 어떤 이벤트도 붙지 않는다 (`SessionClosed`) | `server/services/session/pipeline.py` |
| 오디오가 멈추면 마지막 구간을 닫는다 (`stt_idle_flush_ms`) | `server/services/stt/session.py` |
| 중지 자리에 무음을 끼워 화자 분리가 이음매를 본다 | `server/services/stt/session.py` |
| 종료 확인 대기가 서버 마무리 시간을 견딘다 | `front/components/application.tsx` |

남은 절차는 이 문서의 승인 조건인 재현 검사다. `back` 단위 검사 618건은 통과했지만 실제 스택이 필요한 `node scripts/voice-qa.cjs` 는 아직 돌리지 않았다.

## 재현 명령과 근거

실제 로컬 스택을 띄운 상태에서:

```powershell
cd front
node scripts/integration-findings.cjs
node scripts/voice-qa.cjs
```

- `integration-findings`는 두 TEXT 입력을 비교하고 저장된 음성 세션의 종료 이후 이벤트를 대조한다. 두 문제를 모두 재현했으며 실패 종료코드 1을 반환한다.
- `voice-qa`는 음성 연동뿐 아니라 숫자 경보와 종료 후 이벤트 없음도 승인 조건으로 검사한다. 문제가 있으면 통과로 보고하지 않는다.
- 상세: Git 제외 `front/qa-output/integration-findings.json`, `voice-qa.json`, `voice-live.png`.
- 테스트 세션은 감사/재현을 위해 DB에 보존했다. 기존 규정 후보를 임의 승인하거나 새 운영 팩을 발행하지 않았다.

저장소의 담당 경계(`back/server`: M1, `back/engine`: M2)와 사용자 요청의 front 파일 경계를 지켜 백엔드 코드는 변경하지 않았다. 해당 범위 수정 승인 또는 담당자 반영 후 이 두 회귀 검사를 다시 통과시켜야 최종 완료다.
