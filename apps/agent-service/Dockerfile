FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN groupadd --system trip && useradd --system --gid trip --home /app trip
# opencv-python (bundled by rapidocr-onnxruntime) needs X11/GL shared libs
# that python:3.12-slim omits; without them cv2 fails to import at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxcb1 libx11-6 libxext6 libxrender1 libsm6 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_HTTP_TIMEOUT=120 \
    UV_HTTP_RETRIES=5
COPY apps/agent-service/pyproject.toml apps/agent-service/uv.lock ./
RUN uv sync --frozen --no-dev --all-extras --no-install-project
COPY apps/agent-service/src ./src
RUN uv sync --frozen --no-dev --all-extras
# 链接解析：B站(bilibili-api-python 过 412)、知乎(curl_cffi 浏览器TLS指纹过挑战页)
RUN uv pip install --python /app/.venv/bin/python --no-cache \
    "curl_cffi>=0.13.0,<0.15.0" \
    "bilibili-api-python>=17.4.1,<18.0.0"
COPY knowledge/sources ./knowledge/sources
COPY knowledge/guangzhou ./knowledge/guangzhou
USER trip
CMD ["/app/.venv/bin/trip-agent-worker"]
