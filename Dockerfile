FROM oven/bun:1.3.4-debian AS bun-bin

FROM denoland/deno:2.5.6 AS single-file-build

ARG SINGLE_FILE_CLI_VERSION=2.0.83

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl patch \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /src

RUN curl -fsSL \
    "https://github.com/gildas-lormeau/single-file-cli/archive/refs/tags/v${SINGLE_FILE_CLI_VERSION}.tar.gz" \
    | tar -xz --strip-components=1

COPY docker/single-file-existing-tab.patch /tmp/single-file-existing-tab.patch

RUN patch -p1 < /tmp/single-file-existing-tab.patch \
  && deno compile \
    --allow-read \
    --allow-write \
    --allow-net \
    --allow-env \
    --allow-run \
    --ext=js \
    --output=/out/single-file \
    ./single-file

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

ARG YT_DLP_VERSION=2026.06.09

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/app/backend/.venv

WORKDIR /app/backend

COPY --from=ghcr.io/astral-sh/uv:0.9.21 /uv /uvx /usr/local/bin/
COPY --from=bun-bin /usr/local/bin/bun /usr/local/bin/bun
COPY --from=single-file-build /out/single-file /usr/local/bin/single-file
COPY --from=single-file-build /src /usr/local/share/single-file-cli-source

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg nodejs python3 \
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

RUN --mount=type=cache,target=/root/.cache/reader-fastembed \
  /app/backend/.venv/bin/python - <<'PY'
from pathlib import Path
from shutil import copytree, rmtree

from fastembed import TextEmbedding

cache_dir = Path("/root/.cache/reader-fastembed")
image_dir = Path("/app/models/fastembed")
model = TextEmbedding(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    cache_dir=str(cache_dir),
)
list(model.embed(["Reader semantic search warmup"]))
if image_dir.exists():
    rmtree(image_dir)
copytree(cache_dir, image_dir)
PY

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY scripts /app/scripts
COPY --from=frontend-build /frontend /app/frontend
COPY docker/custom-services.d/reader-api /custom-services.d/reader-api
COPY docker/wrapped-chrome /usr/bin/wrapped-chrome

RUN chmod 0755 /custom-services.d/reader-api
RUN chmod 0755 /usr/bin/wrapped-chrome
