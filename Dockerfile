# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- frontend build
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RTS_DATA_DIR=/data \
    RTS_FRONTEND_DIR=/app/frontend/dist \
    RTS_INSTALL_TYPE=docker

# tini forwards signals and reaps zombies (task processes run as children).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 rts \
    && mkdir -p /data \
    && chown rts:rts /data

WORKDIR /app/backend
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/rts ./rts
RUN pip install ".[postgres]"

COPY --from=web /web/dist /app/frontend/dist

USER rts
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)" || exit 1

ENTRYPOINT ["tini", "--"]
# API (serves the UI too). The worker uses the same image with command "rts-worker".
CMD ["uvicorn", "rts.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
