> 원본: `/tmp/claude-1000/-home-me-projects-malteum/bbf490dd-cf08-4bfa-9747-5dcbfa88b71b/scratchpad/nv_asr/RESULT.md`, 2026-09-03

# NVIDIA 스트리밍 ASR + 화자 분리 실험 — 2026-09-03

목표: NVIDIA 가 2025~2026 년에 공개한 ASR 모델 중 (가) 실시간 스트리밍 (나) 화자 분리/다중 화자 전사 (다) 한국어 지원을 모두 만족하는 모델을 찾고, CPU 에서 시연 음원 두 개로 시험.

## 1. 후보 조사 (Hugging Face nvidia 조직 · NeMo 문서 · 모델 카드 기준)

| 모델 (HF, 공개일) | 스트리밍 | 화자 분리 / 다중 화자 | 한국어 | 라이선스 | CPU 실행 | 비고 |
|---|---|---|---|---|---|---|
| `nvidia/nemotron-3.5-asr-streaming-0.6b` (2026-05) | **O** cache-aware FastConformer-RNNT, 청크 80 ms~1.12 s | **X** (단일 화자 전사, 화자 정보 없음) | **O** ko-KR (transcription-ready 19 개 로케일에 포함, FLEURS CER 7.1~7.6 %) | OpenMDW-1.1 (허용적) | O (이번 실험에서 확인) | 40 로케일, `.nemo` 2.37 GB, NeMo 3.0.0 으로 로드됨 |
| `nvidia/multitalker-parakeet-streaming-0.6b-v1` (2025-10) | O (Nemotron-Speech-Streaming 기반, 80 ms~1.12 s) | **O** Streaming Sortformer v2/v2.1 의 화자 활동을 입력받아 화자별 전사 (`SpeakerTaggedASR`, 화자당 1 인스턴스) | **X** 학습 데이터가 영어 + 유럽어(MLS, VoxPopuli, Europarl 등), 한국어 없음. 모델 카드의 language 배지는 주석 처리됨 | NVIDIA Open Model License | 가능할 것 (미시험) | 세 조건 중 한국어만 빠짐 |
| `nvidia/nemotron-speech-streaming-en-0.6b` (2025-12) | O | X | X (영어 전용) | OpenMDW | O | 3.5 의 전신 |
| `nvidia/parakeet-tdt-0.6b-v3` (2025-08) | X (오프라인 TDT; 버퍼링으로 유사 스트리밍만) | X | X (유럽 25 개 언어) | CC-BY-4.0 | O | |
| `nvidia/canary-1b-v2` (2025-08), `canary-1b-flash`, `canary-qwen-2.5b` | X (오프라인 AED) | X | X (유럽 25 개 언어 / 영어) | CC-BY-4.0 | 느림 (1B, `.nemo` 6.4 GB) | 커뮤니티 파인튜닝 `lee1jun/kanary-1b-pre-v0.1` 이 한국어를 붙였으나 NVIDIA 공식 아님 |
| `nvidia/parakeet-unified-en-0.6b` (2026-04), `parakeet_realtime_eou_120m-v1` | 일부 O | X | X (영어) | | | |
| `nvidia/diar_streaming_sortformer_4spk-v2` / `v2.1` (2025-06/10), `diar_sortformer_4spk-v1` | v2/v2.1 O | 화자 분리 전용 (전사 없음) | 언어 무관 | CC-BY-4.0 | O (앞선 `../diar` 실험) | 최대 4 화자 |
| 구형 `stt_kr_conformer_*` (NGC) | X | X | O | | | HF nvidia 조직에는 없음(커뮤니티 미러 `eesungkim/stt_kr_conformer_transducer_large`). 2023 년 이전 |

**결론: 세 조건을 모두 만족하는 NVIDIA 공개 모델은 없다.** 다중 화자 스트리밍 ASR 인 Multitalker Parakeet 는 영어/유럽어 전용이고, 한국어 스트리밍 ASR 인 Nemotron 3.5 ASR 은 화자 정보를 내지 않는다.
가장 가까운 조합은 **Nemotron 3.5 ASR (ko-KR, 스트리밍) + Streaming Sortformer v2 를 따로 돌려 타임스탬프로 합치기**이며, 이번에 이 조합을 CPU 에서 시험했다.

참고: Multitalker Parakeet 는 구조상 "Nemotron-Speech-Streaming 인코더 + Sortformer 화자 활동 입력"이라 NVIDIA 가 Nemotron 3.5(다국어) 기반 multitalker 를 내면 세 조건이 한 번에 충족될 수 있다. 2026-09 현재 그런 모델은 없다.

## 2. 실행 환경

- CPU 전용, 24 코어 / 30 GB RAM. `../diar/.venv` 재사용 (Python 3.11, torch 2.14.0+cpu, nemo_toolkit[asr] 3.0.0, transformers 5.16.1). 추가 설치 없음.
- 모델 다운로드: `nemotron-3.5-asr-streaming-0.6b.nemo` 2.37 GB, 약 50 초.
- 모델 로드: 29~31 초 (`ASRModel.from_pretrained`, 클래스 `EncDecRNNTBPEModelWithPrompt`). 언어는 `set_inference_prompt("ko-KR")`(스트리밍) / `transcribe(..., target_lang="ko-KR")`(오프라인) 로 지정.
- NeMo 3.0.0 의 함정 두 가지: (1) 오프라인 `transcribe()` 에 파일 경로만 주면 데이터셋이 `lang` 필드를 요구해 `Unknown prompt key: 'None'` 으로 죽는다 → `{"audio_filepath","duration","text":"","lang":"ko-KR"}` 매니페스트를 넘겨 우회. (2) 오프라인 출력에 `<ko-KR>` 언어 태그가 문장마다 섞여 나온다 → 평가에서 제거 (스트리밍 경로는 `decoding.set_strip_lang_tags(True)` 로 제거됨).
- 화자 분리는 앞선 실험의 `../diar/streaming_out.json` (Streaming Sortformer v2, 두 음원 모두 16/16) 을 그대로 사용.

## 3. 방법

- **오프라인**: `transcribe(timestamps=True)` 로 단어 타임스탬프를 받아 단어 중점 시각 → Sortformer 세그먼트로 화자 부여. (이 모델의 기본 att_context 가 `[56,3]` 이라 "오프라인"도 사실상 320 ms 청크 스트리밍 인코더와 같은 결과를 낸다.)
- **스트리밍 시뮬레이션**: `CacheAwareStreamingAudioBuffer` + `conformer_stream_step` 으로 파일을 청크 단위 순차 투입. 청크 1.12 s (`att_context_size=[56,13]`) 와 0.32 s (`[56,3]`) 두 설정. 각 스텝에서 새로 늘어난 텍스트를 그 청크 구간에 균등 배치해 시각을 추정(단어 타임스탬프 없음).
- **평가** (`merge_eval.py`): 정답 줄 구간 [start_ms, start_ms+클립 길이] 에 (1.5 s 여유) 들어오는 단어를 그 줄의 전사로 모아 CER(공백·문장부호 제거 후 Levenshtein / 정답 글자 수) 계산. 줄 화자 = 단어들의 Sortformer 화자 다수결, speaker_0/1 ↔ teller/customer 는 최적 1:1 매핑. 중요 용어는 전체 전사에서 표기 변형(십사퍼센트, 일억, 디에스알 등)까지 허용해 검색.

## 4. 결과

### (가) 전사 품질

| 설정 | dep-a 전체 CER (정답 표기 기준) | dep-a (구어 표기 `tts_text` 기준) | loan-b 전체 CER | loan-b (구어 기준) | 줄 단위 합산 CER dep-a / loan-b |
|---|---|---|---|---|---|
| 오프라인(단어 타임스탬프) | 9.2 % | 6.1 % | 6.3 % | 2.8 % | 9.2 % / 6.3 % |
| 스트리밍 0.32 s 청크 | 9.2 % | 6.1 % | 6.3 % | 2.8 % | 11.1 % / 7.3 % |
| 스트리밍 1.12 s 청크 | 7.4 % | 4.3 % | 6.5 % | 3.0 % | 15.1 % / 11.5 % |

- "정답 표기 기준" CER 의 상당 부분은 숫자 표기 차이다. 모델은 역정규화(ITN)를 하지 않아 `14%`→`십사퍼센트`, `15.4%`→`십오점사퍼센트`, `4.5%`→`연사점 오퍼센트`, `1억`→`일억`, `14일`→`십사일`, `3년`→`삼년` 으로 낸다. 구어 표기 기준으로 보면 3~6 % 수준.
- 스트리밍의 "줄 단위 합산 CER" 이 전체 CER 보다 큰 것은 전사 자체가 아니라 시각 추정이 거칠어(청크 단위) 줄 경계의 "네", "아", "그리고" 같은 첫 단어가 옆 줄로 새기 때문이다. 단어 타임스탬프가 있는 오프라인 경로는 새지 않았다.
- 반복 오류 유형: 어미 첨가(`하시면`→`하시면은`), 동음 혼동(`정기예금`→`전기예금`, `상환`→`상황`, `결재`→`결제`, `약정이율`→`약전기율`), 영문 약어(`DSR`→`디에스를`/`디 에스 알`/`디 에이`).

중요 용어 검출 (전체 전사에서, 표기 변형 허용):

| 용어 | 오프라인 / 0.32 s | 1.12 s | 비고 |
|---|---|---|---|
| 우대이자율, 기본이자율, 과세, 예금자보호, 딸이 알려준 계좌 | O | O | 그대로 나옴 |
| 14%, 15.4%, 1억 | O (십사퍼센트 / 십오점사퍼센트 / 일억) | O | 숫자는 한글 표기 → 판정 전 ITN 필요 |
| 중도해지이율 | **X** (`중도해지율`, `중도해지 이유는`) | O (A12 에서 `중도 해지 이율`) | 설정에 따라 갈림 |
| 차감률 | O | **X** (`차갑률`) | 설정에 따라 갈림 |
| DSR / 총부채원리금상환비율 | O (`총부채원리 금상환 비율`; DSR 은 `디에스를`) | O (`디에스알`) | 영문 약어는 불안정 |
| 무조건 승인됩니다, 연체가산이자율 | O | O | |
| 다른 상환방식은 안 | **X** (`다른 상황방식은 안`) | **X** | `상환`→`상황` 일관 오류 |
| 3% | **X** (`연산퍼센트`, "연 삼 퍼센트" 를 잘못 붙임) | **X** | 결정적 수치 누락 |

15 개 용어 중 오프라인 12 개, 1.12 s 스트리밍 12 개 검출(변형 허용). 두 설정 모두에서 놓친 것은 `다른 상환방식은 안`, `3%` 두 개.

### (나) 화자

세 설정 모두 두 음원에서 **16/16 줄 정답** (매핑 speaker_1=teller, speaker_0=customer). ASR 이 아니라 Sortformer 가 맞힌 것이고, 단어 시각으로 합치는 단계에서 오류가 생기지 않았다는 뜻이다.

### (다) 처리 시간·메모리 (CPU 8 스레드, 147 s / 128 s 음원)

| 설정 | 추론 시간 dep-a / loan-b | 실시간 대비 | 스텝 수 | 스텝당 평균 / 최대 | 피크 RSS |
|---|---|---|---|---|---|
| 오프라인 | 7.1 s / 8.0 s | ~0.05× | — | — | 6.4 GB |
| 스트리밍 1.12 s 청크 | 11.4 s / 9.7 s | ~0.08× | 132 / 115 | 87 ms / 171 ms | 5.8 GB |
| 스트리밍 0.32 s 청크 | 31.3 s / 27.0 s | ~0.21× | 461 / 400 | 68 ms / 110 ms | 5.8 GB |

- 스트리밍 지연 = 청크 길이(알고리즘 지연 0.32 s 또는 1.12 s) + 스텝 계산 시간(70~90 ms). CPU 에서 0.32 s 청크도 여유 있게 실시간(청크당 320 ms 예산에 68 ms 사용). 동시 스트림은 코어 수에 비례해 줄어든다.
- Sortformer v2 는 별도 프로세스에서 8 스레드 1.6 s(전체 파일), RSS 약 2 GB (앞선 실험). 두 모델을 합치면 CPU 서버에서 약 8 GB.
- 참고: 실험 중 offline/stream 두 프로세스를 동시에 돌린 구간이 있어 절대 시간은 10~20 % 보수적으로 볼 것.

## 5. Deepgram 을 대체할 수 있는가

부분적으로만 가능하다. 화자 분리는 Streaming Sortformer 가 이 음원에서 완벽하고, 한국어 스트리밍 ASR 도 Nemotron 3.5 ASR 이 CPU 에서 실시간의 4~10 배 여유로 돌아가며 구어 기준 CER 3~6 % 로 쓸 만하다. 그러나 (1) NVIDIA 에는 한국어 + 스트리밍 + 화자 태깅을 한 모델에서 내는 것이 없어 두 모델을 따로 돌리고 단어 타임스탬프로 합치는 접착 코드를 직접 유지해야 하고, 스트리밍 경로에는 단어 타임스탬프가 없어(청크 단위 추정) 줄 경계 첫 단어가 옆 화자로 새는 문제를 별도로 풀어야 한다. (2) 숫자를 한글로 뱉고(`십오점사퍼센트`) ITN 이 없어 `15.4%` 같은 판정 핵심 수치를 쓰려면 한국어 ITN 후처리(예: NeMo text_processing 의 ko 문법 유무 확인 필요)를 붙여야 하며, 이번 음원에서도 `3%`, `다른 상환방식은 안` 두 핵심 구절을 놓쳤다. (3) 도메인 용어(`상환`→`상황`, `DSR`) 오류는 파인튜닝이나 키워드 부스팅 없이는 남는다. 즉 "Deepgram 없이 자체 CPU 서버로 화자 구분 한국어 실시간 전사"는 기술적으로 성립하지만, 지금 상태로는 Deepgram 급의 즉시 사용성(단어 시각·ITN·화자 라벨이 한 응답에 오는 것)은 아니고 2~4 주 정도의 접착·후처리 작업과 실제 창구 녹음으로의 재검증이 필요하다. 배치 후처리(파일 단위) 용도라면 오프라인 경로가 이미 충분히 쓸 만하다.

## 6. 파일

- `run_offline.py` → `offline_out.json` (단어 타임스탬프 포함), `run_stream.py <right_ctx>` → `stream_out_rc13.json`, `stream_out_rc3.json`
- `merge_eval.py <out.json>` → `*_eval.json`, 사람이 읽는 출력 `eval_offline.txt`, `eval_rc13.txt`, `eval_rc3.txt` (줄별 GT/HYP 대조)
- 모델 카드 사본 `nemotron35_README.md`, `multitalker_README.md`, NeMo 예제 `cache_aware_example.py`, 로그 `*.log`
