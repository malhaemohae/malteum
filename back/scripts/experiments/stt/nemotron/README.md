# nemotron — NVIDIA Nemotron 3.5 ASR Streaming 0.6B 실측(한국어) + Sortformer 결합 평가

원본: `nv_asr/` (스크래치, 2026-09-03). 수치·판단·후보 조사 표는 `RESULT.md` 참고.

## 실행 환경

- CPU 전용(GPU 없음). `../sortformer` 실험과 같은 가상환경(`uv venv --python 3.11`, torch 2.14.0+cpu, `nemo_toolkit[asr]` 3.0.0)을 재사용했다.
- 화자 분리는 `../sortformer` 의 스트리밍 Sortformer v2 결과(`streaming_out.json`)를 그대로 입력으로 쓴다.
- 스크립트 안 절대 경로(스크래치, `/home/me/projects/share/scenarios/...`, `../diar/streaming_out.json`)는 그대로 두었다. **재현하려면 이 경로를 자기 환경에 맞게 바꿔야 한다.**
- `.venv*/`, 모델 캐시(`.nemo` 2.37 GB), 로그는 옮기지 않았다(재현 시 생김).

## 재현 명령

```bash
uv venv --python 3.11 .venv && . .venv/bin/activate
uv pip install torch nemo_toolkit[asr]

python run_offline.py                    # → offline_out.json (단어 타임스탬프 포함)
python run_stream.py 13                  # → stream_out_rc13.json (청크 1.12s, att_context_size=[56,13])
python run_stream.py 3                   # → stream_out_rc3.json  (청크 0.32s, att_context_size=[56,3])

python merge_eval.py offline_out.json    # → offline_out_eval.json, eval_offline.txt
python merge_eval.py stream_out_rc13.json
python merge_eval.py stream_out_rc3.json
```

`merge_eval.py` 는 `../qwen_asr` 의 `eval_qwen.py` 에서도 수정 없이 그대로 호출하는 공통 평가 스크립트다.
