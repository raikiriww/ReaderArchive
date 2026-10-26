FROM oven/bun:1.3.4-debian AS bun-bin

FROM denoland/deno:2.5.6 AS single-file-build

ARG SINGLE_FILE_CLI_VERSION=2.6.1

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl patch \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /src

RUN curl -fsSL \
    "https://github.com/gildas-lormeau/single-file-cli/archive/refs/tags/v${SINGLE_FILE_CLI_VERSION}.tar.gz" \
    | tar -xz --strip-components=1

COPY docker/single-file-existing-tab.patch /tmp/single-file-existing-tab.patch
COPY docker/single-file-navigation.test.js /tmp/single-file-navigation.test.js

RUN patch -p1 < /tmp/single-file-existing-tab.patch \
  && deno test --node-modules-dir=auto --allow-read --allow-write /tmp/single-file-navigation.test.js \
  && deno compile \
    --node-modules-dir=auto \
    --minimum-dependency-age=0 \
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

ARG YT_DLP_VERSION=2026.08.19

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

# The base image sets HOME=/config, a declared volume. Keep the uv cache in a
# build cache mount so it reaches neither an image layer nor new volumes.
RUN --mount=type=cache,target=/root/.cache/uv \
  env -u VIRTUAL_ENV UV_CACHE_DIR=/root/.cache/uv uv sync --locked --no-dev --no-install-project

# Ship both search models in the image, so upgrades need no compose setting and
# no network download. Each model is the official tokenizer and config at a
# pinned revision plus a pinned, checksummed 8-bit ONNX export that onnxruntime
# runs. MiniLM is no longer shipped; it is downloaded only if chosen.
RUN --mount=type=cache,target=/root/.cache/reader-models \
  HF_HOME=/root/.cache/reader-models/hf /app/backend/.venv/bin/python - <<'PY'
import hashlib
import json
from pathlib import Path
from shutil import copyfile

from huggingface_hub import hf_hub_download

cache = '/root/.cache/reader-models'
models = {
    '/app/models/qwen': dict(
        model_name='Qwen/Qwen3-Embedding-0.6B',
        revision='97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3',
        files=['config.json', 'tokenizer.json', 'tokenizer_config.json'],
        # Apache-2.0. 8-bit weights with fp32 activations (MatMulNBits).
        onnx=dict(repo='Qdrant/Qwen3-Embedding-0.6B-onnx',
                  revision='af95f2c416ffe9379369ad64f9113e865db6112c',
                  file='onnx/model_quantized.onnx',
                  sha256='b39d0623bfc7d2dfc2dcc0d32152c5c5b8d61e9e74679e8222dcce5cf32486b9'),
    ),
    '/app/models/reranker': dict(
        model_name='BAAI/bge-reranker-v2-m3',
        revision='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e',
        files=['config.json', 'tokenizer.json', 'tokenizer_config.json'],
        # Hugging Face's onnx-community int8 export of the Apache-2.0 model.
        onnx=dict(repo='onnx-community/bge-reranker-v2-m3-ONNX',
                  revision='6f5ff65298512715a1e669753bc754d2bc8f367b',
                  file='onnx/model_int8.onnx',
                  sha256='912fc1215c2dbff6499700534bd8d31253af01573861abbfc43afd1fab6cce5d'),
    ),
}
for target, spec in models.items():
    directory = Path(target)
    directory.mkdir(parents=True)
    for name in spec['files']:
        copyfile(hf_hub_download(spec['model_name'], name, revision=spec['revision'],
                                 cache_dir=cache), directory / name)
    onnx = spec['onnx']
    source = hf_hub_download(onnx['repo'], onnx['file'], revision=onnx['revision'], cache_dir=cache)
    digest = hashlib.sha256()
    with open(source, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    if digest.hexdigest() != onnx['sha256']:
        raise SystemExit(f"Checksum mismatch for {onnx['repo']}/{onnx['file']}")
    copyfile(source, directory / 'model.onnx')
    (directory / 'reader-model.json').write_text(json.dumps({
        'model_name': spec['model_name'], 'revision': spec['revision'],
        'onnx_repo': onnx['repo'], 'onnx_revision': onnx['revision'], 'onnx_file': onnx['file'],
    }))
PY

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY scripts /app/scripts
# The backend serves only the built pages. Docker verification copies the
# frontend sources in and installs their dependencies when it needs them.
COPY --from=frontend-build /frontend/dist /app/frontend/dist
COPY docker/custom-services.d/reader-api /custom-services.d/reader-api
COPY docker/wrapped-chrome /usr/bin/wrapped-chrome

RUN chmod 0755 /custom-services.d/reader-api
RUN chmod 0755 /usr/bin/wrapped-chrome
