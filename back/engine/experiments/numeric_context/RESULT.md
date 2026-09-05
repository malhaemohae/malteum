# 로컬 ASR 숫자 발화 회귀 실험 (2026-09-05)

## 목적과 기준선

숫자 원문을 교정하지 않고, 로컬 ASR이 출력한 구어 수치와 팩의 근거 수치를 대조한다.
MVP의 외부 LLM 호출과 온프레미스 전환 가능성을 구분하기 위해 STT는 로컬에서 실행하고,
LLM은 요청한 OpenRouter Qwen3-8B·32B로 검증한다. 이 실험은 온프레미스 LLM의 성능이나
데이터 비유출을 실증한 결과가 아니다.

- 변경 전: `dev`의 “Merge pull request #24 from malhaemohae/codex/session-history-recovery”
  커밋 `6171c1f`를 별도 worktree에서 실행했다.
- 변경 후: `feat/engine-numeric-context`. 숫자 대조와 관련 테스트만 수정했다.
- 기존 기준선은 `make test` 487 passed, 2 skipped였다.
- 최종 `make test`는 **560 passed, 2 skipped**였고 ruff·import-linter·생성 모델 검사도 통과했다.
  숫자 표현·문맥·오탐 회귀 테스트 73개를 포함한다.
- 기존 결과의 의미와 조건은 다음 문서를 먼저 확인했다.
  - [STT·화자 분리 온프레미스 경로](../../../../docs/실험/2026-09_STT_화자분리_온프레미스_경로.md)
  - [화자 단계 E2E 실측](../../../../docs/실험/2026-09-04_화자단계_E2E_실측.md)
  - [Qwen ASR 실측](../../../scripts/experiments/stt/qwen_asr/RESULT.md)
  - [화자 역할 모델 비교](../../../scripts/experiments/stt/speaker_infer/RESULT.md)

## 저장된 로컬 전사문으로 변경 전후 비교

기존 Qwen3-ASR 0.6B·1.7B와 Nemotron의 전사 결과 12벌을 재사용했다. 두 TTS 대본의
32줄씩 총 384줄이며, 모델·실행 방식이 다른 반복 자료다. 서로 독립적인 상담 384건을
뜻하지 않는다. ElevenLabs와 GPT 전사는 이 비교에서 제외했다. 화자 라벨은 대본 정답을
사용하고 LLM·L2 없이 L1만 실행하므로, 화자 추정 정확도나 전체 파이프라인 정확도와 다르다.

| 측정 항목 | 변경 전 | 변경 후 |
|---|---:|---:|
| 세율 14%·15.4%, 가정 금리 4.5%의 값·단위 추출 | 4/36 | 36/36 |
| 잘못 안내한 세율 14% 경보 | 3/12 | 12/12 |
| 숫자 발화 72줄의 기대 경보 일치 | 63/72 | 72/72 |
| 위 72줄 중 정상·비교 제외 60줄의 오탐 | 0/60 | 0/60 |
| 대본의 L1 기대 판정(item·axis·state) | 130/156 | 130/156 |

384줄의 verdict는 변경 전후 완전히 같다. 숫자 경보만 늘었다. 이전 L1 생존율 스크립트는
기대 문자열이 `L1`으로 끝나는 항목만 셌지만, 여기서는 뒤에 `missing=...`가 붙은 두 항목도
포함했다. `missing_elements` 자체의 정확도를 재는 지표는 아니다.

숫자 발화 72줄은 A03(잘못된 세율), A11(정정한 세율), B06(가정 금리), B12(중도상환 기간),
B13(연체가산금리), B14(청약철회 기간) × 12벌이다. B06에는 해당 가정 금리의 비교 근거가
없으므로, 숫자를 추출하더라도 수치 불일치 경보는 내지 않는 것이 기대 동작이다.

### 서버와 같은 문장 분리 후 재생

같은 자료에 기존 `server.services.stt.assembler.utterances`를 적용하면 669개 발화가 된다.
같은 전사 줄에서 나온 문장에는 동일한 시각을 부여했다. 대본의 시각과 정답 화자를 쓰므로
실시간 ASR·화자 분리의 지연을 재현하는 실험은 아니다.

| 측정 항목 | 변경 전 | 변경 후 |
|---|---:|---:|
| 잘못 안내한 세율 14% 경보 | 1/12 | 12/12 |
| 숫자 발화 72줄의 기대 경보 일치(문장을 원래 줄로 합산) | 61/72 | 72/72 |
| 다른 줄의 숫자 경보 | 0 | 0 |

기존 verdict 누락은 없었다. Qwen 1.7B 두 자료의 B13에서 `연 삼 퍼센트`를 숫자로 인식하면서
연체가산금리의 L1 partial 판정이 각 1건 추가됐다. 해당 문장에는 대출이자율 설명이 없으므로
완전 충족으로 올리지 않았다. 나머지 667개 발화의 verdict는 동일하다.

실측에서 보완한 표현은 `15점사 퍼센트`, `15점 4퍼센트`, `연사점 5%`, `십사퍼 센트`다.
또한 STT가 같은 구간의 문장들에 같은 시각·길이를 부여하는 경우에는 문장 사이 간격을 0으로
계산한다. 직전 은행원 발화·신뢰도·10초 제한과 주제 모호성 검사는 유지한다.

최종 코드의 L1 경로를 각 50회 예열 후 1,000회씩 측정한 p95는 한 발화 세율 0.147ms,
분리 세율 0.122ms, 대출 금리 두 개 0.271ms였다. L2·LLM 없는 이 세 입력에서는 L1 예산
5ms 이내였다. 전체 서버 지연이나 다양한 입력의 부하 시험 결과를 뜻하지 않는다.

## 실제 TTS → 로컬 STT → 엔진 실행

- 입력: 저장소 `assets/scenarios/{preset-dep-a,preset-loan-b}/audio.wav`.
  예금 147.432625초, 대출 127.79875초를 실시간 속도로 재생했다.
- STT: 로컬 RTX 4070 12GB, 기존 `qwen3-asr-vllm:0.14.0` 이미지,
  `Qwen/Qwen3-ASR-1.7B`, `http://127.0.0.1:18100/v1/audio/transcriptions`.
  `HF_HUB_OFFLINE=1`로 기존 가중치를 사용했고 STT API 키는 빈 값으로 덮어썼다.
- 화자 분리: 로컬 Streaming Sortformer CPU 4스레드, 12프레임(0.96초).
- L2: 로컬 `intfloat/multilingual-e5-small`, 384차원.
- 화자 역할·L3: OpenRouter의 `qwen/qwen3-8b` 또는 `qwen/qwen3-32b`, reasoning off.
- `speaker_hold_ms=3000`, `l3_budget_ms=3000`. 모델 사이에 서버를 재시작해 결정 캐시를 비웠다.
- DB·서버·사이드카는 별도 실험 인스턴스를 사용했다. 저장소 `.env`는 변경하지 않았다.

이번 Qwen 1.7B 전사에서 세금 주제와 14%는 쉼표로 연결된 한 발화였다. 이 사례에서는
변경 전 엔진도 경보를 내므로, E2E에서 숫자 경보가 나왔다는 사실을 분리 발화 개선으로
계산하지 않는다. 분리 발화 개선 수치는 앞 절의 동일 전사문 비교에서 확인한다.

| 모델 / 시나리오 | 충족 | 부분 충족 | 미충족 | 위반 확정 | 경보 | 조력 채택 |
|---|---:|---:|---:|---:|---:|---:|
| 예금 기대 | 4 | 1 | 1 | 1 | 3 | 2 |
| 8B / 예금 | 4 | 1 | 1 | 1 | 3 | 2 |
| 32B / 예금 | 2 | 1 | 3 | 0 | 3 | 1 |
| 대출 기대 | 5 | 0 | 2 | 2 | 2 | 미지정 |
| 8B / 대출 | 5 | 0 | 2 | 2 | 2 | 1 |
| 32B / 대출 | 5 | 0 | 2 | 0 | 2 | 1 |

8B의 두 요약은 대본 기대값과 일치했다. 32B는 L3 제한 시간 초과가 9회 발생했고,
위반 확정을 포함한 L3 결과가 누락됐다. 8B에서는 해당 초과 로그가 없었다. 8B 재생 초기에
전체 테스트 실행이 일부 겹쳤으므로 이 E2E 실행끼리 정밀한 지연 비교는 하지 않는다.
네 세션 모두 종료 이벤트 뒤에 추가 이벤트가 없었다.

E2E 실행 중·이후 보완한 숫자 표현 처리까지 포함한 최종 엔진으로 실제 발화 100개를 다시
재생했다. 변경 전후 verdict와 숫자 경보는 100개 모두 동일했다. 이 대조는 L1만 재생한 것이며,
동일 음원을 변경 전 서버에서 다시 전사하거나 L3를 다시 호출한 실험은 아니다.

원본 이벤트와 음원 SHA-256은 다음 파일에 보존했다.
[8B 예금](qwen8b_preset-dep-a.json), [8B 대출](qwen8b_preset-loan-b.json),
[32B 예금](qwen32b_preset-dep-a.json), [32B 대출](qwen32b_preset-loan-b.json).
입력별 숫자 해석·경보·verdict의 변경 내역은 [comparison.json](comparison.json)에 있다.

## OpenRouter LLM 판정 품질 반복 비교

기존 `scripts/compare_llm.py`의 `run_model`을 재사용했다. `judge_cases`의 L3 사례 4개를
각 3회 실행하고, 8B와 32B 및 변경 전후를 순차 실행했다. 매 반복마다 결정 캐시를 새로
만들었다. L2는 기존 FakeEmbedder로 후보를 고정하고, reasoning off, L3 예산 120초,
어댑터 timeout 90초를 사용했다. 이 표는 실제 음원이나 실시간 3초 제한을 검증하는 표가 아니다.

| 모델 | 변경 전 정답 | 변경 후 정답 | 전/후 p50 | 전/후 최대 |
|---|---:|---:|---:|---:|
| Qwen3-8B | 12/12 | 12/12 | 1.45 / 1.48초 | 2.72 / 3.94초 |
| Qwen3-32B | 9/12 | 9/12 | 4.16 / 3.71초 | 9.45 / 16.87초 |

두 모델 모두 변경 전후 12개 판정 내용이 각각 동일했고 호출 오류는 없었다.
32B는 “중도해지하시면 이자가 좀 줄어듭니다”에서 partial을 맞혔지만, 누락 목록에
`차감률 또는 산출식`만 반환하고 `적용 이율`을 빠뜨렸다. 동일한 실패가 전후 각 3회였다.
비교 스크립트의 `extra=3`은 누락 목록이 다른 튜플 3개를 뜻하며, 판정을 3개 더 만든 것이 아니다.

8B도 별도 품질 실험에서 한 호출이 3초를 넘었다. 작은 표본의 성공률을 운영 SLA로 해석하지
않는다. 특히 OpenRouter 지연은 로컬 GPU에서 LLM을 실행한 지연으로 옮겨 쓸 수 없다.
기존 화자 역할 비교의 46문장 정확도와도 평가 대상이 다르다.

사례별 원본 판정·토큰·소요 시간은 [llm.json](llm.json)에 있다.

## 재현

기존 전사 자료의 비교는 외부 호출 없이 실행한다. `back/`에서:

```sh
uv run python tests/engine/numeric_audio_check.py --engine-root .. --output /tmp/after.json
uv run python tests/engine/numeric_audio_check.py --engine-root /tmp/malteum-baseline --output /tmp/before.json
uv run python tests/engine/numeric_audio_check.py --engine-root .. --split-sentences --output /tmp/after-split.json
```

`--engine-root`는 비교할 저장소 checkout 경로다. `--events <기록.json> ...`를 추가하면
저장된 E2E 이벤트의 실제 시각·길이·화자·신뢰도를 그대로 사용해 L1에 재생한다.
결과 JSON에는 입력 전사문, 추출한 숫자, 기대값, verdict와 숫자 경보가 들어 있다.

실물 재생은 위 구성으로 로컬 서버를 `127.0.0.1:18000`에 실행한 뒤 수행한다. 서버 실행 시
`APP_STT_PROVIDER=openai_file`, `APP_STT_BASE_URL=http://127.0.0.1:18100`,
`APP_STT_MODEL=Qwen/Qwen3-ASR-1.7B`, `APP_STT_API_KEY=`를 반드시 명시해야 한다.
LLM은 `.env`의 OpenRouter 키를 사용하며 모델과 reasoning 설정을 명시한다.

```sh
NUMERIC_OUTPUT_DIR=/tmp/numeric-8b uv run python tests/engine/numeric_audio_replay.py
```

LLM 비교는 비교하려는 checkout의 `back/`에서 아래처럼 실행한다. 기존 CLI의 병렬 실행을
피하고 모델마다 순차 호출한다. OpenRouter 키는 기존 Settings가 읽으며 출력하지 않는다.

```python
import json
from pathlib import Path
from scripts.compare_llm import run_model
from server.bootstrap.settings import Settings

settings = Settings(llm_provider="openrouter")
reports = [
    run_model(model, settings, 3, True)
    for model in ("qwen/qwen3-8b", "qwen/qwen3-32b")
]
Path("/tmp/llm-results.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2))
```

## 해석의 한계

두 음원은 화자 교대에 무음이 있는 합성 TTS다. 실제 창구의 잡음·겹침·사투리를 대표하지 않는다.
ASR이 발음 자체를 다른 수치로 인식하는 오류는 이번 변경으로 복구하지 않는다. 한글 정수는
0~9999, 소수는 낱자리 표현만 해석하며, 여러 발화를 건너뛰는 문맥 추정은 하지 않는다.
입력 원문은 그대로 남기고 근거를 특정할 수 있는 숫자만 대조한다.

초기에 실행한 GPT 전사 기반 실험은 로컬 검증 자료에 포함하지 않았다. 당시 합성 음원 일부가
외부 STT로 전송된 사실은 별개이며, 이후 실행에서는 로컬 STT 주소를 명시했다.
