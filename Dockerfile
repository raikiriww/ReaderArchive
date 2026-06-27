FROM oven/bun:1.3.4-debian AS bun-bin

FROM node:22-bookworm-slim AS frontend-build

COPY --from=bun-bin /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /frontend

COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile

COPY frontend/index.html frontend/openapi.json frontend/openapi-ts.config.ts frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts ./
COPY frontend/public ./public
COPY frontend/src ./src
COPY frontend/tests ./tests

RUN bun run build

FROM lscr.io/linuxserver/chrome:latest

ARG SINGLE_FILE_CLI_VERSION=2.0.83
ARG SINGLE_FILE_CLI_ARCH=x86_64-linux
ARG YT_DLP_VERSION=2026.06.09

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/app/backend/.venv

WORKDIR /app/backend

COPY --from=ghcr.io/astral-sh/uv:0.9.21 /uv /uvx /usr/local/bin/
COPY --from=bun-bin /usr/local/bin/bun /usr/local/bin/bun

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg nodejs python3 \
  && curl -fsSL \
    -o /usr/local/bin/single-file \
    "https://github.com/gildas-lormeau/single-file-cli/releases/download/v${SINGLE_FILE_CLI_VERSION}/single-file-${SINGLE_FILE_CLI_ARCH}" \
  && curl -fsSL \
    -o /usr/local/bin/yt-dlp \
    "https://github.com/yt-dlp/yt-dlp/releases/download/${YT_DLP_VERSION}/yt-dlp" \
  && chmod 0755 /usr/local/bin/single-file \
  && chmod 0755 /usr/local/bin/yt-dlp \
  && /usr/local/bin/single-file --version \
  && /usr/local/bin/yt-dlp --version \
  && ffmpeg -version \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/uv.lock ./

RUN env -u VIRTUAL_ENV uv sync --locked --no-dev --no-install-project

RUN /app/backend/.venv/bin/python - <<'PY'
from fastembed import TextEmbedding

model = TextEmbedding(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    cache_dir="/app/models/fastembed",
)
list(model.embed(["Reader semantic search warmup"]))
PY

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY scripts /app/scripts
COPY --from=frontend-build /frontend /app/frontend
COPY docker/custom-services.d/reader-api /custom-services.d/reader-api

RUN chmod 0755 /custom-services.d/reader-api
