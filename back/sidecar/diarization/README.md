# 화자 분리 사이드카 (Streaming Sortformer)

서버(`back/server`)와 **다른 프로세스·다른 가상환경**으로 선다. NeMo 는 서버보다 의존성이
훨씬 크고(피크 RSS 약 1.8 GB) 화자 분리를 빼고 배포하는 경로도 남겨야 하기 때문이다.
경계는 WebSocket 하나뿐이다.

| | |
|---|---|
| 받는다 | `ws://<host>:<port>/ws` 로 오는 16kHz mono PCM16 바이너리 프레임 |
| 보낸다 | 청크(0.96초)마다 `{"segments": [{"start_ms", "end_ms", "speaker_id"}, ...]}` |
| 상태 확인 | `GET /health` |

돌려주는 것은 **지금까지의 구간 목록 전체**다. Sortformer 는 뒤 오디오를 보고 앞 구간을
고쳐 잡으므로 받는 쪽은 목록을 통째로 갈아 끼워야 한다.

## 실행

가상환경은 청크 축소 실험(`back/scripts/experiments/stt/sortformer_chunk/`)에서 쓴 것을
그대로 재사용한다. NeMo 설치가 오래 걸려서 새로 만들 이유가 없다.

```bash
SCRATCH=/tmp/claude-1000/-home-me-projects-malteum/bbf490dd-cf08-4bfa-9747-5dcbfa88b71b/scratchpad/diar
"$SCRATCH/.venv/bin/python" back/sidecar/diarization/service.py --port 8300
```

새로 만들 때는 이 폴더의 `pyproject.toml` 대로 깔면 된다(`uv sync` 또는
`pip install -e .`). 파이썬은 3.10~3.11 이다 — `nemo_toolkit 3.0.0` 이 도는 범위다.

옵션: `--host`(기본 127.0.0.1) · `--port`(기본 8300) · `--chunk-frames`(기본 12 =
0.96초, DEC-6) · `--threads`(기본 4, `torch.set_num_threads`).

첫 요청 전에 모델을 올린다. 가중치가 `~/.cache/huggingface` 에 있으면 몇 초, 없으면
내려받는 시간이 더 걸린다.

## 서버에 붙이기

```
APP_DIARIZATION_URL=ws://127.0.0.1:8300/ws
```

비워 두면 서버는 화자 분리 공급원 없이 돌고, 발화는 예전처럼 `teller` 고정에
`speaker_confidence` 는 계약 기본값 None 으로 나간다.

## 실물 확인

`back/scripts/diarization_check.py` 가 음원 파일을 실시간 속도로 흘려 줄 단위 정확도와
라벨 지연을 찍는다. 서버 `.venv` 로 돈다.

```bash
cd back
.venv/bin/python scripts/diarization_check.py --url ws://127.0.0.1:8300/ws \
    --scenario preset-dep-a --scenario preset-loan-b
```

## 청크 12프레임(0.96초)인 이유 — DEC-6

`back/scripts/experiments/stt/sortformer_chunk/RESULT.md` 실측이다. 청크를 15초에서
0.96초로 줄여도 시연 음원 32줄의 정확도가 32/32 로 같았고 되돌림도 0건인데, 라벨 지연만
8.16초 → 0.58초로 줄었다. 청크 한 번이 CPU 4스레드에서 평균 0.113초(최대 0.162초)라
실시간의 12 % 만 쓴다.
