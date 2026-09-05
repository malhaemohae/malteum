"""Streaming Sortformer 를 청크 단위로 실제 스트림처럼 돌려 청크 처리 시간·라벨 지연·되돌림을 기록한다.

실행:
  <scratch>/diar/.venv/bin/python run_chunks.py

산출:
  out_<N>s.json  (N = 15, 5, 2, 1, 실제 청크 길이는 프레임 단위로 반올림되어 N 초와 약간 다를 수 있다)
"""
import json
import sys
import time
import resource

import numpy as np
import torch

torch.set_num_threads(4)

from nemo.collections.asr.models import SortformerEncLabelModel  # noqa: E402
from nemo.collections.asr.parts.utils.vad_utils import (  # noqa: E402
    ts_vad_post_processing,
    load_postprocessing_from_yaml,
)
from nemo.collections.asr.parts.utils.speaker_utils import generate_diarization_output_lines  # noqa: E402
import nemo.collections.asr as nemo_asr  # noqa: E402

# nemo.agents.voice_agent.pipecat.services.nemo.utils.CacheFeatureBufferer 를 그대로 쓰고 싶지만
# 그 모듈은 import 시점에 pipecat-ai 패키지를 요구한다(설치돼 있지 않고 이 실험엔 불필요).
# 필요한 두 클래스만 그대로 옮겨왔다(원본: nemo/agents/voice_agent/pipecat/services/nemo/utils.py).
LOG_MEL_ZERO = -16.635


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
    def __init__(self, sample_rate, buffer_size_in_secs, chunk_size_in_secs, preprocessor_cfg, device):
        self.device = device
        self.ZERO_LEVEL_SPEC_DB_VAL = LOG_MEL_ZERO if getattr(preprocessor_cfg, "log", False) else LOG_MEL_ZERO
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
            [self.n_feat, self.feature_buffer_len], self.ZERO_LEVEL_SPEC_DB_VAL, dtype=torch.float32, device=device
        )
        self.preprocessor = nemo_asr.models.ASRModel.from_config_dict(preprocessor_cfg)
        self.preprocessor.to(device)

    def _update_feature_buffer(self, feat_chunk):
        self.feature_buffer[:, : -self.feature_chunk_len] = self.feature_buffer[:, self.feature_chunk_len :].clone()
        self.feature_buffer[:, -self.feature_chunk_len :] = feat_chunk.clone()

    def preprocess(self, audio_signal):
        audio_signal = audio_signal.unsqueeze_(0).to(self.device)
        audio_signal_len = torch.tensor([audio_signal.shape[1]], device=self.device)
        features, _ = self.preprocessor(input_signal=audio_signal, length=audio_signal_len)
        return features.squeeze()

    def update(self, audio):
        self.sample_buffer.update(audio)
        import math

        if math.isclose(self.buffer_size_in_secs, self.chunk_size_in_secs):
            samples = self.sample_buffer.sample_buffer.clone()
        else:
            samples = self.sample_buffer.sample_buffer[-(self.n_chunk_look_back + self.chunk_size) :]
        features = self.preprocess(samples)
        if (diff := features.shape[1] - self.feature_chunk_len - 1) > 0:
            features = features[:, :-diff]
        self._update_feature_buffer(features[:, -self.feature_chunk_len :])

    def get_feature_buffer(self):
        return self.feature_buffer.clone()

SCENARIOS = ["preset-dep-a", "preset-loan-b"]
FRAME_S = 0.08  # 모델 서브샘플 프레임 길이 (80ms)
SAMPLE_RATE = 16000
LEFT_OFFSET = 8  # CacheFeatureBufferer 좌우 문맥 (10ms 프레임 단위, 참고 구현 기본값 유지)
RIGHT_OFFSET = 8
CHUNK_CANDIDATES_S = [15, 5, 2, 1]

POSTPROC = load_postprocessing_from_yaml(None)


def load_audio(path):
    import soundfile as sf

    audio, sr = sf.read(path, dtype="float32")
    assert sr == SAMPLE_RATE, f"unexpected sample rate {sr}"
    if audio.ndim > 1:
        audio = audio[:, 0]
    return audio


def preds_to_segments(preds):
    """preds: [1, T, num_spk] cumulative sigmoid tensor -> ["start end speaker_i", ...] 문자열 리스트."""
    mat = preds.squeeze(0)  # [T, num_spk]
    num_spk = mat.shape[-1]
    speaker_timestamps = [[] for _ in range(num_spk)]
    for spk in range(num_spk):
        ts_mat = ts_vad_post_processing(
            mat[:, spk],
            cfg_vad_params=POSTPROC,
            unit_10ms_frame_count=8,  # subsampling_factor(8) * 10ms = 80ms/frame, offline 경로와 동일
            bypass_postprocessing=False,
        )
        speaker_timestamps[spk] = [[round(a, 3), round(b, 3)] for a, b in ts_mat.tolist()]
    return generate_diarization_output_lines(speaker_timestamps, num_spk)


def segments_overlap_speaker(segments, st, en):
    """[start,end,speaker] 목록에서 [st,en] 구간과 가장 많이 겹치는 화자를 반환."""
    ov = {}
    for line in segments:
        a, b, spk = line.split()
        a, b = float(a), float(b)
        o = max(0.0, min(b, en) - max(a, st))
        if o > 0:
            ov[spk] = ov.get(spk, 0.0) + o
    if not ov:
        return None
    return max(ov, key=ov.get)


def run_one(model, chunk_len_frames, wav_path, script_lines):
    actual_chunk_s = chunk_len_frames * FRAME_S
    chunk_samples = round(actual_chunk_s * SAMPLE_RATE)

    model.sortformer_modules.chunk_len = chunk_len_frames
    model.sortformer_modules.chunk_left_context = 1
    model.sortformer_modules.chunk_right_context = 1
    model.sortformer_modules.fifo_len = 0
    model.sortformer_modules.spkcache_len = 188

    buffer_size_in_secs = actual_chunk_s + (LEFT_OFFSET + RIGHT_OFFSET) * 0.01
    bufferer = CacheFeatureBufferer(
        sample_rate=SAMPLE_RATE,
        buffer_size_in_secs=buffer_size_in_secs,
        chunk_size_in_secs=actual_chunk_s,
        preprocessor_cfg=model.cfg.preprocessor,
        device="cpu",
    )
    streaming_state = model.sortformer_modules.init_streaming_state(
        batch_size=1, async_streaming=model.async_streaming, device="cpu"
    )
    total_preds = torch.zeros((1, 0, 4))

    audio = load_audio(wav_path)
    n_chunks = -(-len(audio) // chunk_samples)  # ceil

    chunk_records = []  # {idx, dt_s, audio_covered_s, finish_s}
    snapshots = []  # (finish_s, audio_covered_s, preds_clone)
    finish_s = 0.0

    for i in range(n_chunks):
        seg = audio[i * chunk_samples : (i + 1) * chunk_samples]
        if len(seg) < chunk_samples:
            seg = np.pad(seg, (0, chunk_samples - len(seg)))

        t0 = time.perf_counter()
        bufferer.update(seg)
        features = bufferer.get_feature_buffer().unsqueeze(0).transpose(1, 2)
        feat_len = torch.tensor([features.shape[1]])
        with torch.inference_mode():
            streaming_state, total_preds = model.forward_streaming_step(
                processed_signal=features,
                processed_signal_length=feat_len,
                streaming_state=streaming_state,
                total_preds=total_preds,
                left_offset=LEFT_OFFSET,
                right_offset=RIGHT_OFFSET,
            )
        dt = time.perf_counter() - t0

        audio_covered_s = min((i + 1) * actual_chunk_s, len(audio) / SAMPLE_RATE)
        arrival_s = (i + 1) * actual_chunk_s  # 실시간으로 청크가 도착했다고 가정한 시각
        finish_s = max(finish_s, arrival_s) + dt  # 처리 큐: 이전 청크 처리가 밀리면 그만큼 늦어짐

        chunk_records.append({"idx": i, "dt_s": dt, "audio_covered_s": audio_covered_s, "finish_s": finish_s})
        snapshots.append((finish_s, audio_covered_s, total_preds.clone()))

    final_segments = preds_to_segments(total_preds)

    # 발화(줄) 단위 라벨 지연 + 온라인 정확도 + 되돌림
    line_results = []
    for l in script_lines:
        en = l["end_s"]
        # 그 줄이 끝난 시점 이후 audio 를 처음으로 커버하는 스냅샷부터 관찰
        first_idx = next((k for k, s in enumerate(snapshots) if s[1] >= en), None)
        if first_idx is None:
            line_results.append({"id": l["id"], "delay_s": None, "reversals": 0, "seq": []})
            continue
        seq = []
        for k in range(first_idx, len(snapshots)):
            finish, _, preds_k = snapshots[k]
            segs_k = preds_to_segments(preds_k)
            spk = segments_overlap_speaker(segs_k, l["start_s"], en)
            if spk is not None:
                seq.append((k, finish, spk))
        delay_s = None
        if seq:
            delay_s = seq[0][1] - en
        reversals = sum(1 for a, b in zip(seq, seq[1:]) if a[2] != b[2])
        line_results.append(
            {
                "id": l["id"],
                "gt_speaker": l["speaker"],
                "delay_s": delay_s,
                "reversals": reversals,
                "first_pred": seq[0][2] if seq else None,
                "final_pred": seq[-1][2] if seq else None,
            }
        )

    return {
        "actual_chunk_s": actual_chunk_s,
        "chunk_len_frames": chunk_len_frames,
        "n_chunks": n_chunks,
        "chunk_records": chunk_records,
        "final_segments": final_segments,
        "line_results": line_results,
    }


def build_script_lines(scenario):
    import wave

    base = f"/home/me/projects/share/scenarios/{scenario}"
    d = json.load(open(f"{base}/script.json"))
    lines = []
    for l in d["lines"]:
        w = wave.open(f"{base}/clips/{l['id']}.wav")
        dur = w.getnframes() / w.getframerate()
        st = l["start_ms"] / 1000
        lines.append({"id": l["id"], "speaker": l["speaker"], "start_s": st, "end_s": st + dur})
    return lines


def main():
    t0 = time.time()
    model = SortformerEncLabelModel.from_pretrained("nvidia/diar_streaming_sortformer_4spk-v2", map_location="cpu")
    model.eval()
    print("load_s", round(time.time() - t0, 1), flush=True)

    script_lines = {s: build_script_lines(s) for s in SCENARIOS}

    for chunk_s in CHUNK_CANDIDATES_S:
        chunk_len_frames = max(1, round(chunk_s / FRAME_S))
        out = {"requested_chunk_s": chunk_s}
        for scenario in SCENARIOS:
            wav = f"/home/me/projects/share/scenarios/{scenario}/audio.wav"
            t0 = time.time()
            res = run_one(model, chunk_len_frames, wav, script_lines[scenario])
            print(
                scenario,
                "chunk_s=",
                chunk_s,
                "actual=",
                res["actual_chunk_s"],
                "wall=",
                round(time.time() - t0, 1),
                flush=True,
            )
            out[scenario] = res
        peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        out["peak_rss_mb_so_far"] = peak_rss_mb
        fn = f"out_{chunk_s}s.json"
        json.dump(out, open(fn, "w"), ensure_ascii=False, indent=1)
        print("wrote", fn, "peak_rss_mb_so_far", round(peak_rss_mb, 1), flush=True)


if __name__ == "__main__":
    main()
