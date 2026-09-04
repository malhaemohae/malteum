# STT 층 — 새 공급자(어댑터)를 붙이는 법

이 폴더는 "오디오가 들어오면 발화 문장이 나온다" 까지만 맡는다. 화자가 누구인지(`speaker.py`),
문장 분리와 PII 마스킹(`assembler.py`), 판정(engine)은 그 뒤의 일이다. 어댑터를 새로 쓰는 사람은
아래 프로토콜 하나만 맞추면 나머지는 그대로 돈다. 1차 MVP 의 OpenAI Realtime 어댑터가 이 자리다.

## 프로토콜 (`base.py`)

```
SttAdapter.open(on_transcript, keyterms=(), *, diarization=None) -> SttStream
SttStream.send(pcm: bytes)      16kHz mono PCM16 조각 (audioFrame 헤더는 벗겨진 뒤)
SttStream.aclose()              남은 전사를 다 넘기고 닫는다
on_transcript(Transcript)       발화 한 조각마다 await 로 부른다
```

`Transcript` 의 필드와 그것이 어디에 쓰이는지:

| 필드 | 뜻 | 누가 쓰나 |
|---|---|---|
| `text` | 전사 문장 | assembler 가 문장으로 나눠 엔진에 넘긴다 |
| `final` | 확정 여부. `False` 면 중간 전사 | partial 은 저장하지 않고 화면에만 흘린다(계약). 판정은 `final` 만 |
| `start_ms`, `duration_ms` | 말이 시작된 세션 시각과 길이(ms) | **화자 접착의 핵심.** `speaker.py` 가 이 구간과 화자 분리 구간의 겹침으로 화자 번호를 고른다. 없으면 세션 시계로 메우지만 정확도가 떨어진다 |
| `confidence` | 공급자 신뢰도 | 로그·화면 참고용 |
| `speaker_id` | 공급자가 화자 분리를 함께 주면 그 번호 | Deepgram 처럼 번호를 주는 공급자만. 없으면 사이드카 구간으로 접착한다 |

`keyterms` 는 세션 팩의 `jargon_terms` 다. 공급자의 힌트 기능(Deepgram keyterm, OpenAI `prompt`)에
넣는다 — 없으면 `만기후이자율` 이 `만기 후 이자율` 로 갈라진다.

`diarization` 은 그 세션의 화자 분리 공급원이다. 스트리밍 공급자는 무시해도 된다. 발화 단위로만
전사하는 파일 어댑터(`openai_file.py`)는 어디서 끊을지를 이 구간에서 얻는다.

## 있는 구현

| 파일 | 방식 | 화자 번호 | 비고 |
|---|---|---|---|
| `deepgram.py` | WebSocket 스트리밍 | 준다 | `APP_STT_PROVIDER=deepgram`(기본), 키만 있으면 됨 |
| `openai_file.py` | 화자 구간마다 WAV 하나를 `POST {base}/v1/audio/transcriptions` | 안 줌 → 사이드카 필요 | Qwen vLLM(`qwen-asr-serve`)과 OpenAI(`https://api.openai.com`, `gpt-4o-transcribe`) 둘 다 확인됨 |
| (없음) `openai_realtime` | OpenAI Realtime WebSocket | 안 줌 → 사이드카 필요 | 설정값 자리만 있다. 붙이면 `bootstrap/startup.py` `_stt` 의 분기에 끼운다 |

## Realtime 어댑터를 쓸 사람에게

- 서버 VAD 가 주는 `speech_started`/`speech_stopped` 의 오디오 오프셋을 `start_ms`·`duration_ms` 로 옮기면
  화자 접착이 그대로 된다. 전사 완료 이벤트는 `final=True`, 델타는 `final=False` 로.
- `open()` 은 소켓 연결·세션 설정까지 끝내고 돌아온다. 실패하면 예외를 올린다 — ws 가
  `stt_unavailable` 로 바꿔 화면이 text 모드를 제안한다(3층 폴백).
- 화자 분리는 Sortformer 사이드카(`back/sidecar/diarization`, compose 의 `diarization` 서비스)가 준다.
  서버는 `APP_DIARIZATION_URL` 로 붙는다. 어댑터가 할 일은 없다.
- 등록: `settings.py` 의 `stt_provider` Literal 에 이름이 이미 있다(`openai_realtime`). `startup._stt` 에서
  그 이름일 때 어댑터를 만들어 돌려주면 끝. 지금은 경고를 남기고 `None`(오디오 층 없음)이다.

## 확인하는 법

- 단위: `tests/server/test_stt_openai_file.py` 가 가짜 화자 구간·가짜 HTTP 로 어댑터를 도는 예다. 같은 모양으로.
- 실물(파일 어댑터): `scripts/stt_file_check.py` 가 시연 음원 한 편을 실시간 속도로 흘려 줄 수 대비 전사 수를 찍는다.
- E2E: 시연 음원을 replay 세션으로 서버에 흘리고 종료 요약을 `assets/scenarios/<preset>/script.json` 의
  `expected_summary` 와 대조한다. 절차와 결과는 `docs/실험/2026-09-04_화자단계_E2E_실측.md`.
