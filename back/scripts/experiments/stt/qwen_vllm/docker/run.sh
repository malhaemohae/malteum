#!/usr/bin/env bash
# Plain docker equivalent of compose.yaml.  ./run.sh build | ./run.sh <run_stream_vllm.py args...>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"; SCRATCH="$(cd "$ROOT/.." && pwd)"
IMG=qwen3-asr-vllm:0.14.0
HF_CACHE="${HF_CACHE:-/home/me/.cache/huggingface}"
if [ "${1:-}" = build ]; then exec docker build -t "$IMG" "$HERE"; fi
exec docker run --rm --gpus all --ipc=host \
  -v "$ROOT":/work/qwen_vllm \
  -v "$SCRATCH/diar":/work/diar:ro \
  -v /home/me/projects/share/scenarios:/data/scenarios:ro \
  -v "$HF_CACHE":/hf_cache \
  -e VLLM_LOGGING_LEVEL=INFO -e HF_HOME=/hf_cache -e HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-0}" \
  "$IMG" run_stream_vllm.py "$@"
