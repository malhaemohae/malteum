# elevenlabs — ElevenLabs Scribe v1/v2 배치 전사 기준선(자체 화자분리 포함)

원본: `eleven_stt/` (스크래치, 2026-09-04). 이 실험은 RESULT.md 가 없어서 수치는 `scribe_v1_out_eval.json`/`scribe_v2_out_eval.json`(줄 단위 CER, 화자 정확도, 핵심 용어 검출)과 `scribe_v1_out.json`/`scribe_v2_out.json`(API 응답 원문, ElevenLabs 자체 화자분리 결과)에서 직접 옮겼다. 종합표는 `docs/실험/2026-09_STT_화자분리_온프레미스_경로.md` 참고.

## 실행 환경

- ElevenLabs Speech-to-Text API(`scribe_v1`, `scribe_v2`), 로컬 GPU/CPU 불필요. 화자분리는 API 옵션(`diarize=true`)의 결과를 그대로 쓴다(온프레미스 Sortformer 를 쓰지 않은 유일한 실험).
- API 키: `.env` 의 `ELEVENLABS_API_KEY`. 스크립트 안 시나리오 경로(`/home/me/projects/share/scenarios/...`)는 그대로 두었다. **재현하려면 이 경로를 자기 환경에 맞게 바꿔야 한다.**

## 재현 명령

```bash
python run_eleven.py scribe_v1   # → scribe_v1_out.json
python run_eleven.py scribe_v2   # → scribe_v2_out.json
```

CER·용어 검출 등의 평가는 이 실험만 별도 스크립트가 없다(원본에도 없었음) — 다른 실험의 `merge_eval.py` 를 그대로 쓰려면 `scribe_v*_out.json` 의 `words` 배열을 그 스크립트가 기대하는 형식으로 변환해야 한다.
