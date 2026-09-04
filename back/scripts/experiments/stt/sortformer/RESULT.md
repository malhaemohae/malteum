> 원본: `/tmp/claude-1000/-home-me-projects-malteum/bbf490dd-cf08-4bfa-9747-5dcbfa88b71b/scratchpad/diar/RESULT.md`, 2026-09-03

# 로컬 화자 분리(diarization) 실험 결과 — 2026-09-03

## 환경
- CPU 전용 (GPU 없음), 24 코어 / 30 GB RAM, Linux. 시스템 전역 설치 없음.
- 가상환경: `uv venv --python 3.11 .venv` (이 폴더). torch 2.14.0+cpu, nemo_toolkit[asr] 3.0.0. venv 크기 1.9 GB.
- 설치 시간: 약 1분 (uv 캐시 덕분. 콜드 설치라면 torch CPU 휠 + NeMo 의존성으로 수 분 예상). 오류 없음.
- 입력 음원: `/home/me/projects/malteum/assets/scenarios/<id>/audio.wav` 는 존재하지 않음(gitignore). 실제 파일은
  `/home/me/projects/share/scenarios/<id>/{audio.wav, clips/, script.json}` 에 있어 이것을 사용.
  - preset-dep-a: 147.43 s, preset-loan-b: 127.80 s, 둘 다 16 kHz mono PCM16.
  - 정답은 `share/scenarios/<id>/script.json` 의 `lines[].start_ms`(조립 후 실제로 밀린 시각. 레포 쪽 script.json 의 start_ms 와 다름) + `clips/<id>.wav` 길이.

## 시도한 모델
| 모델 | 결과 |
|---|---|
| `nvidia/diar_sortformer_4spk-v1` (오프라인 Sortformer, 118M 파라미터, .nemo 471 MB) | 설치·CPU 실행 성공 |
| `nvidia/diar_streaming_sortformer_4spk-v2` (스트리밍 Sortformer, 450 MB) | 같은 venv 에서 추가 시도, CPU 실행 성공 |
| `pyannote/speaker-diarization-3.1` | 시도하지 않음 (1순위가 성공했고, HF 토큰도 없음) |

두 모델 모두 `SortformerEncLabelModel.from_pretrained(...)` → `model.diarize(audio=[wav])` 로 실행. 토큰 불필요.

## 정확도 (줄 단위)
평가 방식: 각 정답 줄 구간 [start_ms, start_ms + 클립 길이] 에서 가장 많이 겹치는 예측 화자를 그 줄의 예측으로 삼고,
예측 화자 번호 ↔ teller/customer 를 1:1 로 가장 잘 맞는 쪽에 매핑.

| 음원 | 모델 | 예측 화자 수 | 맞은 줄 / 전체 | 틀린 줄 id | 추론 시간(8 스레드) |
|---|---|---|---|---|---|
| preset-dep-a (147 s) | sortformer v1 | 2 | 16 / 16 | 없음 | 3.0 s |
| preset-loan-b (128 s) | sortformer v1 | 2 | 16 / 16 | 없음 | 2.4 s |
| preset-dep-a | streaming sortformer v2 | 2 | 16 / 16 | 없음 | 1.6 s |
| preset-loan-b | streaming sortformer v2 | 2 | 16 / 16 | 없음 | 1.6 s |

매핑은 두 음원 모두 speaker_0 = customer, speaker_1 = teller (customer 가 먼저 말하므로 Sortformer 의 도착 순 정렬과 일치).

구간 순도 (v1 기준): 정답 줄 안에서 다른 화자로 예측된 시간 0.0 s, 정답 줄 밖에 찍힌 예측 0.0 s.
예측 발화 총량은 정답(클립 길이 합)보다 7~8 % 적음 — 클립 앞뒤 무음과 문장 사이 짧은 쉼을 비발화로 처리한 것으로, 화자 오류가 아님.
(dep-a: 정답 111.2 s vs 예측 103.0 s / loan-b: 97.2 s vs 89.0 s, 예측 세그먼트 각 22 개)

## 처리 시간·자원 (sortformer v1, CPU)
- 모델 로드: 약 21~24 s (첫 회 다운로드 제외).
- 추론: 8 스레드 3.0 s / 2.4 s, 2 스레드 5.3 s / 4.3 s, 1 스레드 9.4 s / 7.6 s (147 s / 128 s 음원). 1 스레드에서도 실시간 대비 약 15~17배 빠름.
- 피크 RSS 약 2.1 GB.

## 서비스 적용 판단
- **정확도**: 남/여 두 화자, 턴 사이에 무음이 보장된 시연 음원 조건에서는 두 모델 모두 완벽(32/32 줄, 화자 수 2 정확). 다만 이 음원은 TTS 로 만든 "쉬운" 조건이라 실제 창구 녹음(겹침 발화, 잡음, 비슷한 음색)에서의 성능은 별도 확인이 필요.
- **CPU 서버**: 1~2 스레드로도 실시간의 10배 이상 빠르고 메모리 2 GB 수준이라 CPU 서버에 붙이는 데 부담이 없음. 배치(파일 단위) 후처리라면 v1 을 그대로 써도 됨.
- **실시간 스트리밍**: v1 은 오프라인 모델이라 전체 파일이 있어야 함. 스트리밍 v2 는 청크 단위로 도는 설계(모델 기본 설정 chunk_len=188 프레임 ≈ 15 s, spkcache_len=188, fifo_len=0, 좌우 문맥 1 프레임)이며 이 실험에서는 `diarize()` 로 파일 전체를 한 번에 넣어 돌렸을 뿐, 실제 마이크 스트림에서 청크 단위 저지연 호출(chunk_len 을 줄인 설정)은 시험하지 않았음. 실시간 적용을 하려면 (1) chunk_len 을 줄였을 때의 지연·정확도 트레이드오프 측정, (2) STT(Deepgram) 타임스탬프와 정렬하는 로직이 다음 단계. 두 모델 모두 최대 4 화자 제한이 있으나 창구 시나리오에는 충분.
- 참고: NeMo 의존성이 크므로(venv 1.9 GB) 배포 이미지에 넣을 때는 별도 컨테이너/서비스로 분리하는 편이 낫다.

## 파일
- `run_sortformer.py`, `run_streaming.py` — 실행 스크립트. 출력: `sortformer_out.json`, `streaming_out.json`
- `evaluate.py <out.json>` — 줄 단위 정확도, `purity.py` — 구간 순도, `run_threads.py <n>` — 스레드별 시간
- `install.log`, `venv.log`
