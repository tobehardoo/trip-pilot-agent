FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN groupadd --system trip && useradd --system --gid trip --home /app trip
WORKDIR /app
COPY apps/agent-service/pyproject.toml apps/agent-service/uv.lock ./
COPY apps/agent-service/src ./src
RUN pip install --no-cache-dir uv==0.8.4 && uv sync --frozen --no-dev
COPY knowledge/sources ./knowledge/sources
COPY knowledge/guangzhou ./knowledge/guangzhou
USER trip
CMD ["/app/.venv/bin/trip-agent-worker"]
