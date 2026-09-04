# STT·화자분리 실험 기록

2026-09-03~04 에 세션 스크래치 폴더에서 수행한 STT·화자분리 온프레미스 경로 실험 여섯 건의 스크립트와 결과를 옮기고, 레포에서 직접 실행한 청크 축소 실험(`sortformer_chunk/`) 하나를 더한 폴더다(하위 폴더 일곱 개). 배경과 종합 비교표는 [`docs/실험/2026-09_STT_화자분리_온프레미스_경로.md`](../../../../docs/실험/2026-09_STT_화자분리_온프레미스_경로.md) 를 먼저 읽는다. 각 하위 폴더는 원본 `RESULT.md`(있는 경우, 맨 위에 원본 스크래치 경로·날짜 표기)와 스크립트, 재현 명령이 적힌 `README.md` 를 갖는다.

| 폴더 | 실험 | 요약 |
| --- | --- | --- |
| `sortformer/` | NVIDIA Sortformer 화자분리(오프라인 v1, 스트리밍 v2) | CPU 에서 두 시연 음원 32/32 줄 정확, 8스레드 1.6~3.0s |
| `nemotron/` | Nemotron 3.5 ASR Streaming 0.6B(한국어) + Sortformer 결합 | CPU 실시간 여유(0.05~0.21×), 숫자는 전부 한글 표기 |
| `qwen_asr/` | Qwen3-ASR 0.6B/1.7B(transformers 백엔드) | GPU 기준 용어 검출 최고(1.7B seg 15/15), 스트리밍은 vLLM 알고리즘 시뮬레이션 |
| `qwen_vllm/` | Qwen3-ASR 공식 스트리밍(vLLM 0.14.0, Docker) 실측 | 발화 단위 2s 청크 첫 응답 1.9s, 연속 스트리밍은 1.7B CER 붕괴 |
| `speaker_infer/` | LLM 문장 단위 화자 추정(qwen3-8b/32b) | 프롬프트 보강으로 44/46, 예비 신호로만 채택 |
| `elevenlabs/` | ElevenLabs Scribe v1/v2 배치 전사(자체 화자분리) | 외부 STT 기준선. 화자 32/32, 핵심 용어 15/15 |
| `sortformer_chunk/` | Streaming Sortformer 청크 15·5·2·1초 실스트림 재현(CPU 4스레드) | 모든 청크에서 32/32·되돌림 0, 1초 청크 라벨 지연 평균 0.58s |

## 공통 유의사항

- **가상환경(`.venv*`), 모델 캐시, 로그(`*.log`), 1MB 넘는 파일은 옮기지 않았다.** 재현하면 다시 생긴다. `qwen_vllm/out/` 의 실측 결과 JSON·평가 텍스트는 증거로 남겼고 로그만 뺐다(해당 폴더 README 참고).
- 스크립트 안의 절대 경로(스크래치 폴더, `/home/me/projects/share/scenarios/...`)는 원본 그대로 두었다. **재현하려면 각 스크립트의 경로를 자기 환경에 맞게 바꿔야 한다.** 스크립트 동작 자체는 바꾸지 않았다.
- 일곱 실험은 서로 같은 시연 음원 두 개(`preset-dep-a` 147s, `preset-loan-b` 128s), 같은 핵심 용어 15개, 같은 평가 기준(줄 단위 CER, 화면/발음 표기)을 쓴다. `nemotron/`·`qwen_asr/`·`qwen_vllm/` 는 `nemotron/merge_eval.py` 를 공통 평가 스크립트로 그대로 재사용한다.
