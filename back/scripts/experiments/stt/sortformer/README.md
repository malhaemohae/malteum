# sortformer — NVIDIA Sortformer 화자분리 (오프라인 v1 / 스트리밍 v2), CPU 스레드별 속도

원본: `diar/` (스크래치, 2026-09-03). 수치·판단은 `RESULT.md` 참고.

## 실행 환경

- CPU 전용(GPU 없음). `uv venv --python 3.11 .venv`, torch 2.14.0+cpu, `nemo_toolkit[asr]` 3.0.0.
- 입력 음원 경로가 스크립트에 절대 경로(`/home/me/projects/share/scenarios/<id>/...`)로 박혀 있다. **재현하려면 이 경로를 자기 환경에 맞게 바꿔야 한다.**
- `.venv*/`, 모델 캐시, 로그는 옮기지 않았다(재현 시 생김).

## 재현 명령

```bash
uv venv --python 3.11 .venv && . .venv/bin/activate
uv pip install torch nemo_toolkit[asr]

python run_sortformer.py        # → sortformer_out.json (오프라인 v1)
python run_streaming.py         # → streaming_out.json (스트리밍 v2)
python evaluate.py sortformer_out.json   # 줄 단위 정확도
python purity.py sortformer_out.json     # 구간 순도
python run_threads.py 8         # 스레드 수별 추론 시간
```
