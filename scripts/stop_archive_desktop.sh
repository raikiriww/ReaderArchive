#!/usr/bin/env bash
set -euo pipefail

docker compose -f compose.yaml -f compose.build.yaml stop archive-desktop
