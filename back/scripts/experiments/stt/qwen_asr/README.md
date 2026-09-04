# qwen_asr — Qwen3-ASR 0.6B/1.7B (transformers 백엔드), 발화 단위(seg)·전체(full)·클립(clips)·스트리밍 시뮬

원본: `qwen_asr/` (스크래치, 2026-09-04). 수치·판단은 `RESULT.md` 참고.

## 실행 환경

- GPU: RTX 4070 12GB(주 수치, bf16). CPU 24코어/30GB(참고 수치, fp32).
- 가상환경: `.venv`(CPU, torch 2.14.0+cpu), `.venv_gpu`(CUDA). 둘 다 transformers 4.57.6, `qwen-asr` 0.0.6.
  `../sortformer`·`../nemotron` 의 venv(transformers 5.16)는 `qwen-asr`(4.57 요구)와 버전이 맞지 않아 새로 만들었다.
- vLLM 백엔드(`qwen-asr[vllm]`) 호스트 설치는 `/tmp` 용량 부족으로 실패했다(`../qwen_vllm` 에서 Docker 로 우회). 이 폴더의 스트리밍 결과는 그 알고리즘을 transformers 백엔드 위에 재현한 시뮬레이션이다.
- 화자 분리는 `../sortformer` 의 `streaming_out.json` 을, 평가는 `../nemotron` 의 `merge_eval.py` 를 그대로 재사용한다. 스크립트 안 절대 경로는 그대로 두었다. **재현하려면 이 경로를 자기 환경에 맞게 바꿔야 한다.**
- `.venv*/`, 모델 캐시(0.6B 1.88GB + 1.7B 4.7GB), 로그는 옮기지 않았다(재현 시 생김).

## 재현 명령

```bash
uv venv --python 3.11 .venv_gpu && . .venv_gpu/bin/activate
uv pip install torch qwen-asr

DEV=cuda:0 python run_offline.py Qwen/Qwen3-ASR-0.6B 06b_gpu   # → offline_06b_gpu.json (full/seg/clips 세 모드)
DEV=cuda:0 python run_offline.py Qwen/Qwen3-ASR-1.7B 17b_gpu
python run_stream.py Qwen/Qwen3-ASR-1.7B 17b_gpu 2             # → stream_17b_gpu.json (2s 청크 시뮬레이션)

python eval_qwen.py offline_06b_gpu.json    # → ../nemotron/merge_eval.py 를 그대로 호출
python eval_qwen.py stream_17b_gpu.json
```
