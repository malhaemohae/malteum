# qwen_vllm — Qwen3-ASR 공식 스트리밍(vLLM 0.14.0, Docker) 지연·정확도 실측

원본: `qwen_vllm/` (스크래치, 2026-09-04). 수치·판단은 `RESULT.md` 참고, 명령 순서는 `HOWTO.md` 참고.

## 실행 환경

- GPU: RTX 4070 12GB, Docker(이미지 `qwen3-asr-vllm:0.14.0` = `vllm/vllm-openai:v0.14.0` + `qwen-asr[vllm]==0.0.6`).
- `docker/compose.yaml`·`docker/run.sh` 는 `../sortformer`(Sortformer 구간)와 시나리오 음원 폴더, 호스트 HF 캐시(`~/.cache/huggingface`)를 컨테이너에 마운트한다. 마운트 경로가 스크래치 기준(`../../diar`, `/home/me/projects/share/scenarios`)으로 박혀 있다. **재현하려면 이 경로를 자기 환경(`../sortformer`, 실제 음원 위치)에 맞게 바꿔야 한다.**
- 평가(`eval_vllm.py`)는 호스트에서 `../qwen_asr` 의 GPU venv 로 실행하고, `../nemotron/merge_eval.py` 를 그대로 호출한다.
- `out/` 은 이번 실측의 벽시계·부분 텍스트·평가 결과 JSON 과 평가 텍스트를 그대로 옮긴 것(재현 없이도 바로 대조 가능). 스텝별 `*.log` 는 공통 규칙대로 옮기지 않았다. `.venv*/`, `hf_cache/` 는 옮기지 않았다(재현 시 생김) — `out/` 은 예외로 유지한다(아래 참고).

## 재현 명령 (`HOWTO.md` 요약)

```bash
cd docker && docker build -t qwen3-asr-vllm:0.14.0 .

./run.sh --model Qwen/Qwen3-ASR-1.7B --mode seg  --chunk 2.0 --tag 17b_seg_c2
./run.sh --model Qwen/Qwen3-ASR-1.7B --mode full --chunk 2.0 --tag 17b_full_c2 --max-model-len 8192
# 또는 여섯 설정을 한 번에: ./run_all.sh

cd .. && ../qwen_asr/.venv_gpu/bin/python eval_vllm.py out/17b_seg_c2.json
```

## 참고: `.gitignore` 예외

이 폴더의 `out/` 은 재현 시 새로 생기는 산출물이 아니라 실측 당시 결과(JSON·평가 텍스트)를 그대로 옮긴 증거 파일이라, 다른 실험 폴더와 달리 `.gitignore` 에서 `out/` 을 제외하지 않았다(`.venv*/`, `hf_cache/`, `*.wav`, `*.log` 제외). 재현으로 새 `out/*.json` 을 만들 때는 태그를 바꾸거나 별도 디렉터리를 쓰는 것을 권한다.
