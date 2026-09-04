# Streaming Sortformer 사이드카. 서버 이미지와 따로다 — NeMo 가 무겁고(수 GB) 서버 .venv 와 섞이지 않는다.
# CPU 전용 torch 를 먼저 깔아 CUDA 휠(약 2GB)이 따라오지 않게 한다.
FROM python:3.11-slim
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 ffmpeg git build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml .
RUN pip install "nemo_toolkit[asr]==3.0.0" "aiohttp>=3.9" "soundfile>=0.12"
COPY service.py .
EXPOSE 8300
CMD ["python", "service.py", "--host", "0.0.0.0", "--port", "8300", "--threads", "4"]
