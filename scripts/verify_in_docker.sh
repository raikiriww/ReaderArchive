#!/usr/bin/env bash
set -euo pipefail

SERVICE="${READER_VERIFY_SERVICE:-archive-desktop}"
BASE_URL="${READER_VERIFY_BASE_URL:-http://127.0.0.1:8000}"
HEALTH_URL="${BASE_URL%/}/api/v1/health"
SMOKE_URL="${BASE_URL%/}"
USERNAME="${READER_SMOKE_USERNAME:-reader-smoke-admin}"
PASSWORD="${READER_SMOKE_PASSWORD:-reader-smoke-password}"
VERIFY_SEMANTIC_SEARCH_ENABLED="${READER_VERIFY_SEMANTIC_SEARCH_ENABLED:-false}"
VERIFY_VIDEO_DOWNLOAD_TIMEOUT_SECONDS="${READER_VERIFY_VIDEO_DOWNLOAD_TIMEOUT_SECONDS:-5}"
VERIFY_ARCHIVE_TIMEOUT_SECONDS="${READER_VERIFY_ARCHIVE_TIMEOUT_SECONDS:-30}"
VERIFY_BROWSER_WAIT_DELAY_MS="${READER_VERIFY_BROWSER_WAIT_DELAY_MS:-0}"
VERIFY_BROWSER_LOAD_MAX_TIME_MS="${READER_VERIFY_BROWSER_LOAD_MAX_TIME_MS:-5000}"
VERIFY_BROWSER_CAPTURE_MAX_TIME_MS="${READER_VERIFY_BROWSER_CAPTURE_MAX_TIME_MS:-10000}"
RESTORE_VIDEO_DOWNLOAD_TIMEOUT_SECONDS="${READER_RESTORE_VIDEO_DOWNLOAD_TIMEOUT_SECONDS:-600}"
RESTORE_ARCHIVE_TIMEOUT_SECONDS="${READER_RESTORE_ARCHIVE_TIMEOUT_SECONDS:-120}"
RESTORE_BROWSER_WAIT_DELAY_MS="${READER_RESTORE_BROWSER_WAIT_DELAY_MS:-2000}"
RESTORE_BROWSER_LOAD_MAX_TIME_MS="${READER_RESTORE_BROWSER_LOAD_MAX_TIME_MS:-20000}"
RESTORE_BROWSER_CAPTURE_MAX_TIME_MS="${READER_RESTORE_BROWSER_CAPTURE_MAX_TIME_MS:-60000}"

export READER_SEMANTIC_SEARCH_ENABLED="$VERIFY_SEMANTIC_SEARCH_ENABLED"
export READER_VIDEO_DOWNLOAD_TIMEOUT_SECONDS="$VERIFY_VIDEO_DOWNLOAD_TIMEOUT_SECONDS"
export READER_ARCHIVE_TIMEOUT_SECONDS="$VERIFY_ARCHIVE_TIMEOUT_SECONDS"
export READER_BROWSER_WAIT_DELAY_MS="$VERIFY_BROWSER_WAIT_DELAY_MS"
export READER_BROWSER_LOAD_MAX_TIME_MS="$VERIFY_BROWSER_LOAD_MAX_TIME_MS"
export READER_BROWSER_CAPTURE_MAX_TIME_MS="$VERIFY_BROWSER_CAPTURE_MAX_TIME_MS"

echo "==> Building Docker image"
docker compose build "$SERVICE"

echo "==> Starting PostgreSQL"
docker compose up -d db

echo "==> Restarting Docker containers"
docker compose up -d db "$SERVICE"

echo "==> Waiting for API health"
for attempt in $(seq 1 60); do
  if docker compose exec -T "$SERVICE" curl -fsS "$HEALTH_URL" >/dev/null; then
    break
  fi
  if [ "$attempt" -eq 60 ]; then
    echo "API health check failed: $HEALTH_URL" >&2
    exit 1
  fi
  sleep 2
done

echo "==> Installing test dependencies inside the running container"
docker compose exec -T "$SERVICE" \
  env -u VIRTUAL_ENV UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
  bash -lc "cd /app/backend && uv sync --locked --extra test --no-install-project"

echo "==> Copying tests into the running container"
docker compose exec -T "$SERVICE" rm -rf /app/backend/tests
docker compose cp backend/tests "$SERVICE":/app/backend/tests

TEST_DATABASE_URL="${READER_TEST_DATABASE_URL:-$(docker compose exec -T "$SERVICE" printenv READER_DATABASE_URL)}"

echo "==> Running backend tests inside Docker"
docker compose exec -T "$SERVICE" \
  env READER_TEST_DATABASE_URL="$TEST_DATABASE_URL" \
      READER_BOOTSTRAP_ADMIN_USERNAME=admin \
      READER_BOOTSTRAP_ADMIN_PASSWORD=change-me \
      READER_SEMANTIC_SEARCH_ENABLED=false \
  bash -lc "cd /app/backend && /app/backend/.venv/bin/python -m pytest"

echo "==> Generating frontend client inside Docker"
docker compose exec -T "$SERVICE" \
  bash -lc "cd /app/frontend && bun run generate-client"

echo "==> Ensuring smoke test admin user inside Docker"
docker compose exec -T "$SERVICE" \
  env READER_SMOKE_USERNAME="$USERNAME" \
      READER_SMOKE_PASSWORD="$PASSWORD" \
  bash -lc 'cd /app/backend && /app/backend/.venv/bin/python -m scripts.ensure_smoke_user --username "$READER_SMOKE_USERNAME" --password "$READER_SMOKE_PASSWORD"'

echo "==> Running frontend checks inside Docker"
docker compose exec -T "$SERVICE" \
  bash -lc "cd /app/frontend && bun run check && bun run lint && bun run build"

echo "==> Running frontend unit tests inside Docker"
docker compose exec -T "$SERVICE" \
  bash -lc "cd /app/frontend && bun run test"

if [ "$VERIFY_SEMANTIC_SEARCH_ENABLED" = "false" ]; then
  echo "==> Restoring semantic search in the running Docker service"
  READER_SEMANTIC_SEARCH_ENABLED=true \
    READER_VIDEO_DOWNLOAD_TIMEOUT_SECONDS="$RESTORE_VIDEO_DOWNLOAD_TIMEOUT_SECONDS" \
    READER_ARCHIVE_TIMEOUT_SECONDS="$RESTORE_ARCHIVE_TIMEOUT_SECONDS" \
    READER_BROWSER_WAIT_DELAY_MS="$RESTORE_BROWSER_WAIT_DELAY_MS" \
    READER_BROWSER_LOAD_MAX_TIME_MS="$RESTORE_BROWSER_LOAD_MAX_TIME_MS" \
    READER_BROWSER_CAPTURE_MAX_TIME_MS="$RESTORE_BROWSER_CAPTURE_MAX_TIME_MS" \
    docker compose up -d db "$SERVICE"
  echo "==> Waiting for restored API health"
  for attempt in $(seq 1 60); do
    if docker compose exec -T "$SERVICE" curl -fsS "$HEALTH_URL" >/dev/null; then
      break
    fi
    if [ "$attempt" -eq 60 ]; then
      echo "Restored API health check failed: $HEALTH_URL" >&2
      exit 1
    fi
    sleep 2
  done
fi

echo "==> Docker verification passed"
echo "==> Verification container is still running"
