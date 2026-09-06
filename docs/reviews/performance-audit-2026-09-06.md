# 성능 감사 및 재생 시간 보정 (2026-09-06)

## 범위와 근거

- 기준: `feat/front-ux-polish`, 시작 커밋 `b0943a7`. 착수 시 `git status --short` 출력 없음. 이후 병행 작업의 다른 파일 변경을 확인했으며 해당 파일은 수정하지 않음.
- 쓰기 범위: `back/server/services/stt/audio.py`, `back/server/services/session/replay.py`, `back/tests/server/test_replay_timing.py`, 이 보고서. 커밋·계약 변경·큐 병렬화 없음.
- [실측: 코드 확인]: 현재 소스의 실행 순서·기본값 확인. 운영 설정값이나 성능 실측과 구분함.
- [과거 실측]: 기존 저장소 문서를 이번에 읽어 인용한 값. 현재 공급자·하드웨어·부하에서 재측정한 값이 아님.
- [실측: 가상 시계]: 실제 재생 함수에 소비자 처리 시간을 주입한 결정적 테스트. 공급자·네트워크 성능과 구분함.
- [실측: 로컬 시계]: Python 3.12.10, Windows 이벤트 루프에서 직접 잰 값. 외부 STT(Speech-to-Text: 음성을 문자로 바꾸는 처리)와 LLM(Large Language Model: 대규모 언어 모델)은 호출하지 않음.
- [추정]: 코드 구조에서 도출한 영향·후속 우선순위. 운영 공급자 선택은 확인하지 않았고 `.env` 내용·비밀키는 출력하지 않음.

## 실제 STT → 역할 → 판정 → 보정 흐름

아래 실행 경로는 모두 [실측: 코드 확인]임. 파일명은 저장소 루트 기준이며 `:숫자`는 확인한 줄 번호임.

| 단계 | 실행 경로와 지연 의미 | 근거 |
|---|---|---|
| 오디오 공급 | 재생 generator(요청할 때마다 다음 조각을 내는 함수)의 청크마다 `stt.feed` 완료를 기다림. 마지막에는 전사 종료 처리를 기다림 | `back/server/ws/endpoint.py:335`, `:338` |
| 공통 입력 | 같은 PCM(Pulse-Code Modulation: 샘플로 저장한 음성)을 화자 분리 사이드카에 보낸 뒤 STT에 보냄. 두 처리 시간이 다음 청크 요청에 포함됨 | `back/server/services/stt/session.py:95` |
| 공급자 분기 | `openai_realtime`, `openai_file`, Deepgram 구현이 존재함. 설정 클래스 기본값은 Deepgram이며 실제 배포 선택과 다를 수 있음 | `back/server/bootstrap/startup.py:108`, `:138`, `:163`, `back/server/bootstrap/settings.py:71` |
| OpenAI Realtime | 전송과 수신 태스크를 분리함. VAD(Voice Activity Detection: 발화와 무음을 가르는 처리) 무음 기본값 500ms. partial·final을 콜백에 전달함. 무음 설정값만으로 전사 지연을 계산할 수 없음 | `back/server/services/stt/openai_realtime.py:69`, `:104`, `:151`, `:167` |
| Deepgram | 중간 결과를 요청하고 별도 수신 루프에서 전사 콜백을 기다림. 코드에 endpointing(발화 종료 판단) 시간 설정이 없어 공급자 final 대기는 이 코드만으로 확정하지 않음 | `back/server/services/stt/deepgram.py:43`, `:89` |
| 파일 STT | 화자 분리가 실제로 처리한 시각을 기준으로 구간 뒤 600ms 무음을 확인하고 큐에 넣음. 단일 worker(큐에서 작업을 꺼내 수행하는 실행 단위)가 구간별 전사 요청을 순서대로 기다림. 발화 내부 partial 없음. 요청 timeout 기본값 60초 | `back/server/services/stt/openai_file.py:16`, `:43`, `:60`, `:113`, `:125`, `:147`, `:166` |
| 화자·역할 | final 시각·문장을 조립하며 역할 추론을 먼저 예약함. 발화 도착 시 hold 기한을 정하고, 별도 단일 release 큐가 역할 확정·submit을 차례로 기다림. 기존 확정 역할은 즉시 사용하므로 모든 발화가 3초를 기다리지는 않음 | `back/server/services/stt/session.py:122`, `:127`, `:144`, `back/server/services/stt/speaker.py:209`, `:262`, `:416` |
| 역할 모델 | 동기 호출을 `asyncio.to_thread`로 스레드에 넘김. 모델 timeout 기본값 30초와 발화 hold 기본값 3초는 다른 한도임. 짧은 첫 인사말은 충분한 근거를 기다리는 정책이 적용됨 | `back/server/services/stt/role_judge.py:82`, `:91`, `back/server/services/stt/speaker.py:221`, `:438`, `back/server/bootstrap/settings.py:87` |
| 빠른 판정 | 발화 저장·전송 후 `judge`를 스레드에서 기다림. 내부 순서는 L0 정규화 → L1 규칙 → L2 임베딩 검색임. L1 결과도 L2 완료 후 반환되어야 전송됨. `observe`·`apply`·저장·전송 후 필요할 때 refine 예약 | `back/server/services/session/pipeline.py:76`, `:86`, `:91`, `:98`, `back/engine/engine.py:137`, `:192`, `:213` |
| L3 보정 | 별도 단일 큐에서 순서대로 실행함. 후보 재계산 → 선택적 전사 교정 → 결정 캐시 조회 → 필요시 L3 → 적용 순서임. 비동기 보정이어도 큐 대기는 발생 가능함 | `back/server/services/session/refiner.py:35`, `:38`, `:44`, `back/server/services/session/pipeline.py:108`, `back/engine/graphs/refine/graph.py:23` |
| 저장·전송 | 동기 이벤트 저장 및 SQL 트랜잭션 사용. 화면 전송도 socket 완료를 기다림. 실제 병목 여부는 미측정 | `back/server/services/session/pipeline.py:64`, `:145`, `back/server/services/event/store.py:72`, `back/server/ws/connection.py:37` |
| trace | STT·역할·judge·refine을 호출하지 않음. 원본 이벤트를 순번으로 정렬하고 시점별 fold(이벤트를 적용해 상태를 계산하는 처리) 및 화면 매핑 수행 | `back/server/services/session/replay.py:53`, `:66` |

[추정] 발화 종료 → 최초 판정은 공급자 final 도착, 남은 역할 대기와 앞선 발화 처리, judge 처리, 저장·전송으로 나누어 측정해야 함. L3 확정에는 refine 큐 대기와 graph 전체 처리도 포함됨. 역할 추론은 큐 대기와 겹칠 수 있어 과거 평균을 단순 합산하지 않음. 근거: `back/server/services/stt/session.py:127`, `:148`, `back/server/services/session/refiner.py:48`.

## 과거 기록과 현재 의미

| 구분 | 문서에 남은 값 | 해석과 근거 |
|---|---|---|
| 목표 | 확정 발화 → 화면 p95 1초, L3 1~3초 | [목표, 실측 아님] p95(95th percentile: 관측치 중 95%가 이내에 들어오는 값). 발화 종료부터의 지연과 다름. `docs/기획/핵심기획안.md:351` |
| 화자 분리 | 0.96초 청크에서 평균 0.61초, 최대 1.09초, 두 합성 음원 32/32줄 | [과거 실측] 2026-09-04 CPU(Central Processing Unit: 범용 중앙 처리 장치) 4스레드 Sortformer 측정. 현장 잡음·겹침 발화의 대표값이 아님. `docs/실험/2026-09-04_화자단계_E2E_실측.md:12`, `:18`, `:22` |
| 역할 판정 | 9건, 최소 1.27초 / 평균 1.65초 / 최대 2.36초 | [과거 실측] OpenRouter qwen3-8b 왕복. 현재 응답 속도는 재확인하지 않음. `docs/실험/2026-09-04_화자단계_E2E_실측.md:76`, `:83` |
| L3 refine | 15건, 최소 1.24초 / 평균 1.64초 / 최대 2.06초, 예산 초과 없음 | [과거 실측] 제한된 회차 결과. 같은 문서에 2~5초 변동 이력 및 2회차 결정 캐시 효과도 기록됨. `docs/실험/2026-09-04_화자단계_E2E_실측.md:82`, `:85`, `:86`, `:87` |
| 특정 발화 | B02 L1 판정 +20ms, B03 카드 +18ms | [과거 실측] 특정 시나리오 결과이며 전체 상담의 p95가 아님. `docs/실험/2026-09-04_화자단계_E2E_실측.md:63`, `:64` |
| Qwen 별도 스트리밍 | 1.7B 발화 단위 2초 청크: 첫 부분 평균 1.9초, 최종 평균 0.12초 | [과거 실측] 별도 GPU(Graphics Processing Unit: 병렬 연산 장치)와 공식 스트리밍 실험. 서버 파일 전사·역할·judge·refine 총시간으로 사용 불가. `docs/실험/2026-09_STT_화자분리_온프레미스_경로.md:39`, `:43` |
| 공급자 선택 기록 | 1차 MVP(Minimum Viable Product: 핵심 기능을 검증할 최소 제품) 계획은 외부 OpenAI Realtime 조합 | [문서 확인] 과거 서버 측정은 `openai_file` 조합. 과거 문서의 Realtime 미구현 기록도 현재 코드와 다름. `docs/실험/2026-09_STT_화자분리_온프레미스_경로.md:5`, `docs/실험/2026-09-04_화자단계_E2E_실측.md:11`, `:98`, `back/server/bootstrap/startup.py:108` |

## 이번 수정 및 결과

[실측: 코드 확인] 기존 `b0943a7`의 `audio.py:75-77`은 `yield` 후 매번 100ms를 추가로 쉬었음. 소비자 처리 시간은 그 위에 더해졌음. 기존 `replay.py:59-69`도 fold·publish 처리 후 원본 간격 전체를 다시 기다렸음. `git show b0943a7:back/server/services/stt/audio.py`와 `git show b0943a7:back/server/services/session/replay.py`로 확인 가능함.

| 변경 | 보존한 조건 | 근거 |
|---|---|---|
| 오디오: monotonic clock(시스템 날짜 변경과 독립적인 경과 시간 시계)의 시작 시각 + 누적 바이트 길이로 기한 계산 | 첫 청크 즉시 전달, 동일 순서·전체 바이트, 마지막 부분 청크의 실제 길이까지 시간 보장. 소비자가 늦으면 추가 대기만 0으로 줄임 | `back/server/services/stt/audio.py:74`, `back/tests/server/test_replay_timing.py:47`, `:66`, `:83`, `:102` |
| trace: 음수를 0으로 처리한 원본 간격을 누적해 기한 계산 | 순번, 긴 침묵, 같은 시각·역전 시각의 기존 간격 정책, 시점별 fold, verdict progress, assist 버전, 원본 불변성 보존 | `back/server/services/session/replay.py:55`, `back/tests/server/test_replay_timing.py:166`, `:182`, `:198` |
| 기한 초과 시 `sleep(0)` 유지 | [실측: 코드 확인] 밀린 데이터도 순서대로 보내고 이벤트 루프에 실행 기회를 넘기는 지점 유지 | `back/server/services/stt/audio.py:83`, `back/server/services/session/replay.py:63` |

| 실험 | 기존 결과 | 수정 결과 | 근거 종류 |
|---|---|---|---|
| 10초 오디오, 청크 소비 25ms | 두 번째 청크 0.125초, 마지막 청크 12.375초 | 청크 시각 0.1초 간격, 완료 10초 | [실측: 가상 시계] 초기 실패 출력 및 `test_replay_timing.py:47` |
| 250ms 오디오, 소비 대기 없음 | 완료 300ms | 완료 250ms | [실측: 가상 시계] `test_replay_timing.py:66` |
| trace, fold 50ms·publish 200ms, 원본 오프셋 0/1/2/36.9/37.9초 | 마지막 publish 시작 38.75초 | 마지막 publish 시작 37.95초. 현재 이벤트 fold 50ms는 여전히 필요함 | [실측: 가상 시계] `test_replay_timing.py:166` |
| 오디오, sleep이 매번 5ms 늦게 복귀 | 추가 테스트이므로 기존 결과 별도 기록 없음 | 1초 오디오 종료 1.005초. 이전 sleep 초과가 누적되지 않음 | [실측: 가상 시계] `test_replay_timing.py:244` |
| 2초 오디오, 실제 `asyncio.sleep(0.025)` 소비자, 각각 3회 교차 실행 | 2.812 / 2.813 / 2.812초 | 2.000 / 2.016 / 2.000초. 매회 전체 64,000바이트 전달 | [실측: 로컬 시계] 아래 재현 코드. sleep 요청 시간과 실제 복귀 시간은 다를 수 있음. 외부 서비스 성능 향상률로 환산하지 않음 |
| 음원 헤더 조회 | 비교용 기준 없음 | dep-a 147.432625초, loan-b 127.79875초. 둘 다 16kHz·mono·16bit | [실측: 파일 확인] Python `wave.open`의 `getnframes()/getframerate()` 및 형식 필드 조회 |

- [실측] 수정 전 신규 테스트: `11 failed, 4 passed`. 시간 단언 실패를 확인한 후 생산 코드 수정함.
- [실측] oversleep 사례 추가 후 신규 테스트: `16 passed, 5 warnings in 0.07s`. 경고는 fixture 팩의 기존 `DummyPathWarning`, `back/engine/pack/compiler.py:92`에서 발생함.
- [실측] 서버·엔진 회귀: `344 passed, 4 skipped, 59 warnings in 6.74s`. 건너뛴 테스트를 실물 공급자 검증으로 세지 않음.
- [실측] 수정 Python 파일의 `ruff check`: `All checks passed!`. `ruff format --check`: `3 files already formatted`. 최초 형식 확인에서 신규 테스트 파일이 걸려 그 파일만 정리함.
- 문서 저장 첫 시도는 PowerShell here-string 구분자가 본문의 명령 예시와 충돌해 파싱 단계에서 실패함. 구분자를 분리해 다시 저장했으며 실패한 시도에서 파일 쓰기는 실행되지 않았음.
- 전체 `make test`, 생성 모델·전체 import 경계 검사는 통합 담당의 최종 확인 범위임. 이번 실행은 전체 브랜치 검증을 대신하지 않음.

## 남은 병목과 우선순위

우선순위는 [추정]이며 운영 병목 순위를 확정한 실측은 아님.

| 우선순위 | 병목 후보와 영향 | 다음 검증·판단 | 근거 |
|---|---|---|---|
| P1 | 공급자 final 도착과 초기 역할 확정 대기가 최초 판정을 늦출 수 있음 | 오디오 종료·final 수신·역할 예약/확정·release 진입·submit 완료를 같은 발화로 수집. 신규/확정 화자를 분리 집계. hold를 속도만 보고 축소하지 않음 | `back/server/services/stt/session.py:122`, `:127`, `:148`, `back/server/services/stt/speaker.py:221`, `:262` |
| P1 | 파일 STT·L3 단일 큐에서 느린 작업 뒤로 후속 결과가 밀릴 수 있음 | enqueue → 시작 → 종료 시각 및 큐 길이 측정. L3 상한은 graph 전체·큐 대기의 한도가 아님. 병렬화 전 상태·보정 사슬 정합성 검토 | `back/server/services/stt/openai_file.py:113`, `:166`, `back/server/services/session/refiner.py:35`, `:48`, `back/engine/graphs/refine/nodes.py:122` |
| P1 | L3 바깥 예산 3초와 내부 요청 timeout 30초 및 재시도 정책의 차이. await 취소 후 thread 작업이 계속되면 공유 자원을 점유할 수 있음 | 공급자 요청 timeout·retry와 외부 예산을 함께 계측하고 정렬하는 별도 작업 검토. 설정 변경 없음 | `back/server/bootstrap/settings.py:59`, `back/engine/graphs/refine/nodes.py:125`, `back/engine/adapters/llm/litellm.py:55`, `:74`, `:85` |
| P1 | cold start(모델이 메모리에 없는 첫 실행)의 팩 인덱스 구축·모델 로딩. judge 스레드 이동만으로 첫 세션 로딩까지 보호된다고 볼 수 없음 | 세션 준비와 첫 judge를 별도 측정. 필요시 readiness(요청을 받을 준비 상태)와 연결한 워밍업 검토 | `back/server/ws/endpoint.py:91`, `back/server/services/session/registry.py:108`, `:129`, `back/engine/engine.py:73`, `:85`, `back/engine/adapters/embedder/local.py:29` |
| P2 | L1도 L2 종료를 기다림. refine 후보 계산에서 임베딩을 반복하고 선택적 교정은 결정 캐시보다 앞에 있음 | warm 상태의 L1·L2 및 graph 전체 시간 분리. 상태 의존 결과와 텍스트 임베딩의 재사용 가능성을 구분. 교정은 기본 비활성화임 | `back/engine/engine.py:192`, `:213`, `back/engine/tiers/l2/searcher.py:226`, `back/engine/graphs/refine/nodes.py:74`, `:95`, `back/engine/graphs/refine/graph.py:29`, `back/server/bootstrap/settings.py:50` |
| P2 | trace가 이벤트마다 전체 prefix(현재까지의 앞부분)를 다시 접음. n개 이벤트에 최소 n(n+1)/2개 이벤트 방문 필요 | 원본 길이별 fold 비용 측정. 점진적 fold 검토 시 `supersedes`·버전·요약 동일성을 먼저 검증 | `back/server/services/session/replay.py:66`, `back/engine/state/fold.py:20`, `:26` |
| P2 | 동기 DB(Database: 데이터 저장·조회 시스템) 처리·느린 화면 전송. 파일 STT는 누적 PCM도 보유함 | 저장·조회·전송 지연, 동시 세션 부하와 장시간 녹음 메모리를 측정. 순서·정합성 검증 없이 일괄 비동기 전환하지 않음 | `back/server/services/session/pipeline.py:66`, `:145`, `back/server/services/event/store.py:74`, `back/server/ws/connection.py:48`, `back/server/services/stt/openai_file.py:111`, `:117` |

## 한계와 반론

- [추정] 소비자가 지속적으로 느리면 원본 기한을 맞출 수 없음. 이번 수정은 중복 대기를 제거하며 처리 자체를 빠르게 하지는 않음. 과부하 후에는 밀린 데이터를 짧은 간격으로 전달할 수 있으나 누락·재정렬·묵음 생략은 없음. 근거: `back/server/services/stt/audio.py:79`, `back/server/services/session/replay.py:59`, 과부하 테스트 `back/tests/server/test_replay_timing.py:83`, `:102`, `:190`.
- [실측: 코드 확인] 오디오 전체 길이와 마지막 전사 완료는 별개임. 서버는 스트림 종료 직후 `stt.aclose`를 호출함. 파일 STT 실험 스크립트는 그 전에 1.2초 기다리므로 동일한 종료 조건으로 취급하면 안 됨. 근거: `back/server/ws/endpoint.py:338`, `back/server/services/stt/session.py:102`, `back/scripts/stt_file_check.py:96`. [추정] 누적 여유 대기가 사라진 뒤 마지막 화자 구간이 모두 전사되는지 실물 음원으로 재확인할 필요가 있음. 임의 종료 대기는 추가하지 않음.
- 기각한 대안: 긴 trace 간격 상한, 묵음 건너뛰기, 마지막 청크 뒤 대기 제거. 원본 시간 또는 오디오 전체 길이를 바꾸므로 제외함. 큐 병렬화도 승인된 범위와 상태 순서 검증 부담 때문에 제외함.
- 자기 반박: 절대 기한으로 따라잡으면 일시적인 전송 몰림이 생길 수 있음. 현재 방식은 데이터를 버리지 않고 소비자 흐름 제어를 따름. 몰림을 완전히 금지하면 재생 시간이 늘어나므로 별도 정책 결정이 필요함.
- 임의 결정 보고: 테스트 시계·소비 비용·합성 음원 길이는 재현 가능한 검증을 위한 구현 선택임. 간격 보존·monotonic pacing·쓰기 범위·커밋 금지는 지시로 이미 정해진 조건임.

## 실행 명령

저장소 루트 `C:/Users/hanbin/malteum`의 PowerShell에서 실행함. `-B`는 bytecode 생성을, `-p no:cacheprovider`는 pytest 캐시 기록을 막음. 기존 가상환경을 사용하여 의존성·lock 파일을 갱신하지 않음.

```powershell
& back/.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider back/tests/server/test_replay_timing.py -q --disable-warnings
& back/.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider back/tests/server back/tests/engine -q --disable-warnings
& back/.venv/Scripts/python.exe -B -m ruff check --no-cache back/server/services/stt/audio.py back/server/services/session/replay.py back/tests/server/test_replay_timing.py
& back/.venv/Scripts/python.exe -B -m ruff format --check --no-cache back/server/services/stt/audio.py back/server/services/session/replay.py back/tests/server/test_replay_timing.py
```

로컬 시계 비교 재현. 기준 코드는 Git에서 메모리로만 읽으며 파일·서버·비밀키에 쓰지 않음.

```powershell
@'
import asyncio, json, subprocess, sys, types
from pathlib import Path
sys.path.insert(0, str(Path('back').resolve()))
from server.services.stt import audio
old = types.ModuleType('baseline_audio')
source = subprocess.check_output(
    ['git', 'show', 'b0943a7:back/server/services/stt/audio.py'],
    text=True, encoding='utf-8')
exec(compile(source, '<baseline>', 'exec'), old.__dict__)
async def measure(stream):
    loop = asyncio.get_running_loop()
    started, count = loop.time(), 0
    async for frame in stream(b'\0\0' * 32000):
        count += len(frame)
        await asyncio.sleep(0.025)
    return {'elapsed_s': round(loop.time() - started, 6), 'bytes': count}
async def main():
    result = {'baseline': [], 'fixed': []}
    for _ in range(3):
        result['baseline'].append(await measure(old.stream))
        result['fixed'].append(await measure(audio.stream))
    print(json.dumps(result))
asyncio.run(main())
'@ | & back/.venv/Scripts/python.exe -B -
```

아래는 기존 실물 경로 도구의 후속 실행 예시이며 이번에 실행하지 않았음. 서버·사이드카·선택한 STT·LLM 설정이 준비되어야 하며 `check_scenario.py`는 테스트 세션을 생성함. 공급자별 비용이 발생할 수 있음. 이 도구만으로 단계별 p95를 모두 얻지는 못하므로 위 시각 계측과 함께 사용해야 함.

```powershell
Set-Location C:/Users/hanbin/malteum/back
& .venv/Scripts/python.exe -B scripts/check_scenario.py --all --base http://localhost:8000
& .venv/Scripts/python.exe -B scripts/diarization_check.py --url ws://127.0.0.1:8300/ws
& .venv/Scripts/python.exe -B scripts/stt_file_check.py --scenario preset-dep-a
```

[추정] 후속 실측은 최초·반복 실행을 나누고 결정 캐시 적중·신규 역할 번호·모델·동시 세션 수를 함께 남겨야 함. `TierTrace.l3_ms`는 L3 호출 주변 시간이며 큐 대기·후보 재계산·선택적 교정 전체를 포함하지 않음. 근거: `back/engine/graphs/refine/nodes.py:122`, `:137`, `:158`, `back/engine/graphs/refine/graph.py:23`.
