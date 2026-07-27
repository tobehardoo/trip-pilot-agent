FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN groupadd --system trip && useradd --system --gid trip --home /app trip
WORKDIR /app
ENV UV_HTTP_TIMEOUT=120 \
    UV_HTTP_RETRIES=5
COPY apps/agent-service/pyproject.toml apps/agent-service/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/agent-service/src ./src
RUN uv sync --frozen --no-dev --offline
COPY knowledge/sources ./knowledge/sources
COPY knowledge/guangzhou ./knowledge/guangzhou
USER trip
CMD ["/app/.venv/bin/trip-agent-worker"]
