# Qwen3-ASR 공식 스트리밍(vLLM 백엔드) 컨테이너 실행 순서

경로 기준: `scratchpad/qwen_vllm/` (이 파일이 있는 폴더). 모든 명령은 sudo 없이, docker 그룹 권한만 필요.

## 0. 구성

- `docker/Dockerfile` — `vllm/vllm-openai:v0.14.0` + `qwen-asr[vllm]==0.0.6` (qwen-asr 0.0.6 이 `vllm==0.14.0` 을 고정하므로 이 태그여야 함) + `soundfile`.
  이미지 안의 apt 판 `blinker 1.4` 가 flask 설치를 막아 `pip install --ignore-installed blinker` 를 먼저 한다.
- `docker/compose.yaml`, `docker/run.sh` — 같은 마운트: `..`→`/work/qwen_vllm`(스크립트·`out/`), `../../diar`→`/work/diar`(Sortformer 구간, 읽기 전용),
  `/home/me/projects/share/scenarios`→`/data/scenarios`(읽기 전용), `$HF_CACHE`→`/hf_cache`(모델 가중치).
  `HF_CACHE` 기본값은 `/home/me/.cache/huggingface` (0.6B·1.7B 가 이미 받아져 있음, 6.2 GB). 스크래치 폴더는 quota 가 걸린 tmpfs(`/tmp`, 약 3 GB 여유)라 `hf_cache/` 를 거기 두면 앞선 venv 설치와 같은 `Disk quota exceeded` 로 실패한다. 공간이 있으면 `HF_CACHE=$PWD/hf_cache` 로 바꾸면 된다.
- `run_stream_vllm.py` — 컨테이너 안에서 도는 실측 스크립트(공식 `init_streaming_state / streaming_transcribe / finish_streaming_transcribe` 사용). 결과 `out/<tag>.json`.
- `eval_vllm.py` — 호스트에서 `../qwen_asr/.venv_gpu/bin/python` 으로 실행. `../nv_asr/merge_eval.py` 를 수정 없이 호출해 CER·용어·화자를 내고, 지연·되돌림 통계를 더한다. 결과 `out/eval_<tag>.txt|_merge.json|_summary.json`.

## 1. 빌드

```bash
cd scratchpad/qwen_vllm/docker
docker build -t qwen3-asr-vllm:0.14.0 .          # 또는: docker compose build
```

## 2. 스트리밍 실측 (컨테이너)

```bash
cd scratchpad/qwen_vllm/docker
# 1.7B, Sortformer 발화 단위, 청크 2 s (공식 기본값)
./run.sh --model Qwen/Qwen3-ASR-1.7B --mode seg  --chunk 2.0 --tag 17b_seg_c2
# 1.7B, 발화 단위, 청크 1 s
./run.sh --model Qwen/Qwen3-ASR-1.7B --mode seg  --chunk 1.0 --tag 17b_seg_c1
# 1.7B, 자르지 않고 파일 전체를 연속 스트리밍
./run.sh --model Qwen/Qwen3-ASR-1.7B --mode full --chunk 2.0 --tag 17b_full_c2
# 0.6B (시간이 남으면)
./run.sh --model Qwen/Qwen3-ASR-0.6B --mode seg  --chunk 2.0 --gpu-util 0.6 --tag 06b_seg_c2
```
전부 한 번에: `./run_all.sh` (여섯 설정을 순서대로, 결과 `out/run_all.log`). compose 로는 `docker compose run --rm asr run_stream_vllm.py <같은 인자>`.
`--mode full` 은 147 s 파일 끝에서 프롬프트가 4,100 토큰을 넘으므로 `--max-model-len 8192` 를 붙여야 한다(1.7B 는 `--gpu-util 0.85` 에서 8192 도 KV 캐시가 충분).
옵션: `--push-ms 100`(마이크 push 단위), `--unfixed-chunks 2 --unfixed-tokens 5`(공식 기본), `--gpu-util 0.85 --max-model-len 4096`(vLLM 선점 비율·컨텍스트; 0.6 에서는 KV 캐시 공간 부족으로 엔진이 안 뜸), `--max-new-tokens 32`(공식 예제값).

## 3. 평가 (호스트)

```bash
cd scratchpad/qwen_vllm
../qwen_asr/.venv_gpu/bin/python eval_vllm.py out/17b_seg_c2.json
```
출력: `== preset-…: line-CER … full-transcript CER …` 줄(merge_eval 원문은 `out/eval_<tag>.txt`)과, 태그별 한 줄 요약(rtf, 스텝 시간 mean/p50/max, 첫 부분 전사 지연, 최종 확정 지연, 되돌림 횟수, 아라비아 숫자 여부, 용어 검출).

지연 정의(실시간 재생 시뮬레이션): 청크 i 는 오디오 시각 `audio_end_s` 에 도착하고 GPU 하나가 순서대로 처리한다고 놓고 `done_i = max(arrive_i, done_{i-1}) + lat_i`.
첫 부분 전사 지연 = (첫 비어 있지 않은 텍스트의 `done`) − 발화 시작, 최종 확정 지연 = (finish 스텝 `done`) − 발화 끝.
