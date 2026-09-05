"""Streaming Sortformer 화자 분리 사이드카. WebSocket 하나로 오디오를 받고 구간을 돌려준다.

    받는다   16kHz mono PCM16 바이너리 프레임 (크기는 자유. 안에서 청크로 모은다)
    보낸다   청크마다 {"segments": [{"start_ms", "end_ms", "speaker_id"}, ...],
                      "covered_ms": 이 목록이 어디까지의 오디오를 보고 나온 값인가}

**돌려주는 것은 지금까지의 구간 목록 전체이며 새로 늘어난 부분이 아니다.** Sortformer 는
뒤 오디오를 보고 앞 구간을 고쳐 잡으므로, 받는 쪽이 누적해 이어 붙이면 고쳐진 구간과
옛 구간이 함께 남는다. 받는 쪽(`server/services/stt/diarization.py` 의
`SortformerDiarization`)은 목록을 통째로 갈아 끼운다.

## 왜 프로세스를 나눴나

NeMo 는 서버 `.venv` 보다 의존성이 훨씬 크다(torch + nemo_toolkit[asr], 피크 RSS 약
1.8 GB). 서버에 얹으면 부팅 시간과 이미지가 그만큼 늘고, 화자 분리를 빼고 배포하는
경로가 사라진다. 그래서 경계를 프로세스 사이의 WebSocket 하나로 두었다.

## 청크 12프레임 = 0.96초 (DEC-6)

실측에서 청크를 15초부터 0.96초까지 줄여도 시연 음원 32줄의 정확도가 32/32 로 같았고
라벨이 뒤에 바뀌는 되돌림도 0건이었다(`scripts/experiments/stt/sortformer_chunk/
RESULT.md`). 라벨 지연만 8.2초에서 0.58초로 줄어든다. CPU 4스레드에서 청크 한 번이
평균 0.11초라 실시간의 12 % 만 쓴다.

스트리밍 호출부(`AudioBufferer`·`CacheFeatureBufferer` 포함)는 그 실험의 `run_chunks.py`
에서 그대로 옮겨왔다. 원본은 NeMo 의 `nemo/agents/voice_agent/pipecat/services/nemo/
utils.py` 인데, 그 모듈은 import 시점에 이 서비스에 필요 없는 `pipecat-ai` 를 요구한다.

## 실행

    <venv>/bin/python service.py --port 8300

자세한 것은 같은 폴더 `README.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import time

import torch
from aiohttp import WSMsgType, web

log = logging.getLogger("diarization")

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
FRAME_S = 0.08  # 모델 서브샘플 프레임 길이 (80ms)
CHUNK_FRAMES = 12  # DEC-6. 12 × 80ms = 0.96초
# CacheFeatureBufferer 좌우 문맥 (10ms 프레임 단위, 참고 구현 기본값 유지)
LEFT_OFFSET = 8
RIGHT_OFFSET = 8
MODEL = "nvidia/diar_streaming_sortformer_4spk-v2"
LOG_MEL_ZERO = -16.635
MAX_SPEAKERS = 4


# --- NeMo 참고 구현에서 옮겨 온 두 버퍼 -----------------------------------------
# 원본: nemo/agents/voice_agent/pipecat/services/nemo/utils.py. 그 모듈은 import 시점에
# pipecat-ai 를 요구하는데 이 서비스에는 필요 없어서 두 클래스만 그대로 가져왔다.


class AudioBufferer:
    def __init__(self, sample_rate, buffer_size_in_secs):
        self.buffer_size = int(buffer_size_in_secs * sample_rate)
        self.sample_buffer = torch.zeros(self.buffer_size, dtype=torch.float32)

    def update(self, audio):
        if not isinstance(audio, torch.Tensor):
            audio = torch.from_numpy(audio)
        shift = audio.shape[0]
        self.sample_buffer[:-shift] = self.sample_buffer[shift:].clone()
        self.sample_buffer[-shift:] = audio.clone()


class CacheFeatureBufferer:
    def __init__(
        self, sample_rate, buffer_size_in_secs, chunk_size_in_secs, preprocessor_cfg, device
    ):
        import nemo.collections.asr as nemo_asr

        self.device = device
        self.ZERO_LEVEL_SPEC_DB_VAL = LOG_MEL_ZERO
        self.n_feat = preprocessor_cfg.features
        self.timestep_duration = preprocessor_cfg.window_stride
        self.n_chunk_look_back = int(self.timestep_duration * sample_rate)
        self.chunk_size = int(chunk_size_in_secs * sample_rate)
        self.buffer_size_in_secs = buffer_size_in_secs
        self.chunk_size_in_secs = chunk_size_in_secs
        self.sample_buffer = AudioBufferer(sample_rate, buffer_size_in_secs)
        self.feature_buffer_len = int(buffer_size_in_secs / self.timestep_duration)
        self.feature_chunk_len = int(chunk_size_in_secs / self.timestep_duration)
        self.feature_buffer = torch.full(
            [self.n_feat, self.feature_buffer_len],
            self.ZERO_LEVEL_SPEC_DB_VAL,
            dtype=torch.float32,
            device=device,
        )
        self.preprocessor = nemo_asr.models.ASRModel.from_config_dict(preprocessor_cfg)
        self.preprocessor.to(device)

    def _update_feature_buffer(self, feat_chunk):
        self.feature_buffer[:, : -self.feature_chunk_len] = self.feature_buffer[
            :, self.feature_chunk_len :
        ].clone()
        self.feature_buffer[:, -self.feature_chunk_len :] = feat_chunk.clone()

    def preprocess(self, audio_signal):
        audio_signal = audio_signal.unsqueeze_(0).to(self.device)
        audio_signal_len = torch.tensor([audio_signal.shape[1]], device=self.device)
        features, _ = self.preprocessor(input_signal=audio_signal, length=audio_signal_len)
        return features.squeeze()

    def update(self, audio):
        self.sample_buffer.update(audio)
        if math.isclose(self.buffer_size_in_secs, self.chunk_size_in_secs):
            samples = self.sample_buffer.sample_buffer.clone()
        else:
            samples = self.sample_buffer.sample_buffer[
                -(self.n_chunk_look_back + self.chunk_size) :
            ]
        features = self.preprocess(samples)
        if (diff := features.shape[1] - self.feature_chunk_len - 1) > 0:
            features = features[:, :-diff]
        self._update_feature_buffer(features[:, -self.feature_chunk_len :])

    def get_feature_buffer(self):
        return self.feature_buffer.clone()


# --- 상담 하나 -----------------------------------------------------------------


class DiarizationStream:
    """연결 하나의 스트리밍 상태. 청크가 찰 때마다 한 스텝 돌린다.

    모델 객체는 연결마다 새로 만들지 않고 공유한다(가중치가 크다). 대신 `chunk_len`
    같은 모듈 설정과 스트리밍 상태는 여기서 잡으므로, 서로 다른 청크 길이로 두 상담을
    동시에 받지는 못한다 — 실행 인자로 한 번 정하는 값이라 문제되지 않는다.
    """

    def __init__(self, model, postproc, chunk_frames: int = CHUNK_FRAMES) -> None:
        self.model = model
        self.postproc = postproc
        self.chunk_s = chunk_frames * FRAME_S
        self.chunk_bytes = round(self.chunk_s * SAMPLE_RATE) * BYTES_PER_SAMPLE
        model.sortformer_modules.chunk_len = chunk_frames
        model.sortformer_modules.chunk_left_context = 1
        model.sortformer_modules.chunk_right_context = 1
        model.sortformer_modules.fifo_len = 0
        model.sortformer_modules.spkcache_len = 188
        self.bufferer = CacheFeatureBufferer(
            sample_rate=SAMPLE_RATE,
            buffer_size_in_secs=self.chunk_s + (LEFT_OFFSET + RIGHT_OFFSET) * 0.01,
            chunk_size_in_secs=self.chunk_s,
            preprocessor_cfg=model.cfg.preprocessor,
            device="cpu",
        )
        self.state = model.sortformer_modules.init_streaming_state(
            batch_size=1, async_streaming=model.async_streaming, device="cpu"
        )
        self.preds = torch.zeros((1, 0, MAX_SPEAKERS))
        # 지금까지 모델에 넣은 오디오의 길이. 받는 쪽이 "이 구간 목록이 얼마나 최신인가"
        # 를 알아야 라벨 지연을 잴 수 있다(`scripts/diarization_check.py`)
        self.covered_ms = 0
        self._pending = bytearray()

    def push(self, pcm: bytes) -> None:
        self._pending += pcm

    def ready(self) -> bool:
        return len(self._pending) >= self.chunk_bytes

    def step(self) -> list[dict]:
        """청크 하나를 밀어 넣고 지금까지의 구간 목록 전체를 돌려준다. **블로킹이다.**"""
        chunk = bytes(self._pending[: self.chunk_bytes])
        del self._pending[: self.chunk_bytes]
        self.covered_ms += round(self.chunk_s * 1000)
        samples = torch.frombuffer(bytearray(chunk), dtype=torch.int16).float() / 32768.0
        self.bufferer.update(samples)
        features = self.bufferer.get_feature_buffer().unsqueeze(0).transpose(1, 2)
        with torch.inference_mode():
            self.state, self.preds = self.model.forward_streaming_step(
                processed_signal=features,
                processed_signal_length=torch.tensor([features.shape[1]]),
                streaming_state=self.state,
                total_preds=self.preds,
                left_offset=LEFT_OFFSET,
                right_offset=RIGHT_OFFSET,
            )
        return segments(self.preds, self.postproc)


def segments(preds, postproc) -> list[dict]:
    """누적 예측 텐서 → `{start_ms, end_ms, speaker_id}` 목록. 시간 순서다."""
    from nemo.collections.asr.parts.utils.speaker_utils import generate_diarization_output_lines
    from nemo.collections.asr.parts.utils.vad_utils import ts_vad_post_processing

    matrix = preds.squeeze(0)  # [T, num_spk]
    num_spk = matrix.shape[-1]
    stamps = []
    for speaker in range(num_spk):
        marks = ts_vad_post_processing(
            matrix[:, speaker],
            cfg_vad_params=postproc,
            unit_10ms_frame_count=8,  # subsampling_factor(8) × 10ms = 80ms/frame
            bypass_postprocessing=False,
        )
        stamps.append([[round(a, 3), round(b, 3)] for a, b in marks.tolist()])
    out = []
    for line in generate_diarization_output_lines(stamps, num_spk):
        start, end, speaker_id = line.split()
        out.append(
            {
                "start_ms": round(float(start) * 1000),
                "end_ms": round(float(end) * 1000),
                "speaker_id": speaker_id,
            }
        )
    out.sort(key=lambda s: (s["start_ms"], s["end_ms"]))
    return out


# --- 서버 ----------------------------------------------------------------------


async def handle(request: web.Request) -> web.WebSocketResponse:
    """상담 하나. 오디오를 받아 청크가 찰 때마다 구간 목록을 돌려준다."""
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=0)
    await ws.prepare(request)
    app = request.app
    stream = DiarizationStream(app["model"], app["postproc"], app["chunk_frames"])
    log.info("상담 하나가 붙었습니다 (%s)", request.remote)
    steps = 0
    try:
        async for message in ws:
            if message.type is not WSMsgType.BINARY:
                continue
            stream.push(message.data)
            while stream.ready():
                started = time.perf_counter()
                # 청크 한 번이 CPU 0.11초라 이벤트 루프에서 그냥 돌리면 그동안 다른
                # 상담의 오디오를 못 받는다. 모델 하나를 여럿이 나눠 쓰므로 잠금도 건다
                async with app["lock"]:
                    found = await asyncio.to_thread(stream.step)
                steps += 1
                await ws.send_json({"segments": found, "covered_ms": stream.covered_ms})
                log.debug(
                    "청크 %d: %.3fs, 구간 %d", steps, time.perf_counter() - started, len(found)
                )
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001  상담 하나가 서비스를 끊지 않게 한다
        log.warning("상담 처리 중 예외: %s: %s", type(e).__name__, e)
    finally:
        log.info("상담이 끝났습니다 (청크 %d)", steps)
        await ws.close()
    return ws


async def health(request: web.Request) -> web.Response:
    return web.json_response({"model": MODEL, "chunk_frames": request.app["chunk_frames"]})


def build_app(chunk_frames: int = CHUNK_FRAMES) -> web.Application:
    from nemo.collections.asr.models import SortformerEncLabelModel
    from nemo.collections.asr.parts.utils.vad_utils import load_postprocessing_from_yaml

    started = time.time()
    model = SortformerEncLabelModel.from_pretrained(MODEL, map_location="cpu")
    model.eval()
    log.info("%s 를 %.1f초에 올렸습니다", MODEL, time.time() - started)

    app = web.Application()
    app["model"] = model
    app["postproc"] = load_postprocessing_from_yaml(None)
    app["chunk_frames"] = chunk_frames
    app["lock"] = asyncio.Lock()
    app.add_routes([web.get("/ws", handle), web.get("/health", health)])
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Streaming Sortformer 화자 분리 사이드카")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8300)
    parser.add_argument("--chunk-frames", type=int, default=CHUNK_FRAMES)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    torch.set_num_threads(args.threads)
    web.run_app(build_app(args.chunk_frames), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
