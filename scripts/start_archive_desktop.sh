#!/usr/bin/env bash
set -euo pipefail

if [ ! -f .env ]; then
  cp .env.example .env
fi

mkdir -p data/browser/config data/archive
docker compose -f compose.yaml -f compose.build.yaml up -d archive-desktop
