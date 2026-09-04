# Qwen3-ASR streaming on the official vLLM GPU image.
# qwen-asr 0.0.6 pins vllm==0.14.0 (extra "vllm"), so the base tag must be v0.14.0 — see HOWTO.md.
FROM vllm/vllm-openai:v0.14.0

# vllm==0.14.0 is already present in the image, so the [vllm] extra only adds qwen-asr + its small deps.
# qwen-asr pins transformers==4.57.6; pip may print a resolver warning against vllm's transformers range — that is expected.
# --ignore-installed blinker: the image carries a distutils-installed blinker 1.4 (apt) that pip cannot uninstall for flask.
RUN pip install --no-cache-dir --ignore-installed blinker && pip install --no-cache-dir "qwen-asr[vllm]==0.0.6" soundfile

ENV HF_HOME=/hf_cache \
    PYTHONUNBUFFERED=1 \
    VLLM_LOGGING_LEVEL=WARNING

WORKDIR /work/qwen_vllm
# The base image's entrypoint is the OpenAI API server; we run our own script instead.
ENTRYPOINT ["python3"]
CMD ["run_stream_vllm.py", "--help"]
