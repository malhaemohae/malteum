# sortformer_chunk — Streaming Sortformer 청크 축소 실험 (CPU, 실제 스트림 재현)

원본: 이 폴더에서 직접 실행(2026-09-04, 워크벤치 WB-20260904-ff613c). 수치·해석은 `RESULT.md` 참고.

## 실행 환경

- CPU 전용, `torch.set_num_threads(4)` 고정. 가상환경은 `sortformer/` 실험과 같은 것(Python 3.11, torch 2.14.0+cpu, `nemo_toolkit[asr]` 3.0.0)을 재사용했다. 스크립트가 참조하는 가상환경·음원 경로는 절대 경로라 **재현하려면 자기 환경에 맞게 바꿔야 한다.**
- 모델 `nvidia/diar_streaming_sortformer_4spk-v2` 를 `forward_streaming_step()` 으로 청크마다 직접 호출한다(파일 통째 `diarize()` 가 아님).

## 재현 명령

```bash
cd back/scripts/experiments/stt/sortformer_chunk
<가상환경>/bin/python run_chunks.py     # 청크 15·5·2·1초 × 두 음원 → out_<N>s.json
<가상환경>/bin/python build_result.py   # out_*.json → RESULT.md 표 + table_rows.json
```

## 파일

- `run_chunks.py` 실행 스크립트, `build_result.py` 표 생성, `out_15s.json`·`out_5s.json`·`out_2s.json`·`out_1s.json` 청크별 원시 출력, `table_rows.json` 표 행, `RESULT.md` 결과와 해석.
- 실행 로그(`*.log`)는 공통 규칙대로 옮기지 않았다.
