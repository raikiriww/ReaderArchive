#!/usr/bin/env bash
set -euo pipefail

SERVICE="${READER_VERIFY_SERVICE:-archive-desktop}"
SKIP_BUILD="${READER_VERIFY_SKIP_BUILD:-false}"
BASE_URL="${READER_VERIFY_BASE_URL:-http://127.0.0.1:8000}"
HEALTH_URL="${BASE_URL%/}/api/v1/health"
SMOKE_URL="${BASE_URL%/}"
USERNAME="${READER_SMOKE_USERNAME:-reader-smoke-admin}"
PASSWORD="${READER_SMOKE_PASSWORD:-reader-smoke-password}"
VERIFY_SEMANTIC_SEARCH_ENABLED="${READER_VERIFY_SEMANTIC_SEARCH_ENABLED:-false}"
VERIFY_VIDEO_DOWNLOAD_TIMEOUT_SECONDS="${READER_VERIFY_VIDEO_DOWNLOAD_TIMEOUT_SECONDS:-5}"
VERIFY_ARCHIVE_TIMEOUT_SECONDS="${READER_VERIFY_ARCHIVE_TIMEOUT_SECONDS:-30}"
VERIFY_BROWSER_LOAD_MAX_TIME_MS="${READER_VERIFY_BROWSER_LOAD_MAX_TIME_MS:-5000}"
VERIFY_BROWSER_CAPTURE_MAX_TIME_MS="${READER_VERIFY_BROWSER_CAPTURE_MAX_TIME_MS:-10000}"
RESTORE_VIDEO_DOWNLOAD_TIMEOUT_SECONDS="${READER_RESTORE_VIDEO_DOWNLOAD_TIMEOUT_SECONDS:-600}"
RESTORE_ARCHIVE_TIMEOUT_SECONDS="${READER_RESTORE_ARCHIVE_TIMEOUT_SECONDS:-120}"
RESTORE_BROWSER_LOAD_MAX_TIME_MS="${READER_RESTORE_BROWSER_LOAD_MAX_TIME_MS:-20000}"
RESTORE_BROWSER_CAPTURE_MAX_TIME_MS="${READER_RESTORE_BROWSER_CAPTURE_MAX_TIME_MS:-60000}"
VERIFY_DATA_DIR="${READER_VERIFY_DATA_DIR:-.local_verify/docker}"
VERIFY_POSTGRES_VOLUME="${READER_VERIFY_POSTGRES_VOLUME:-reader_verify_postgres}"
VERIFY_PROJECT_NAME="${READER_VERIFY_COMPOSE_PROJECT_NAME:-reader_verify}"

export COMPOSE_PROJECT_NAME="$VERIFY_PROJECT_NAME"

docker_compose() {
  docker compose -f compose.yaml -f compose.build.yaml "$@"
}

export READER_ARCHIVE_DIR="${READER_ARCHIVE_DIR:-$VERIFY_DATA_DIR/archive}"
export READER_BROWSER_PROFILE_DIR="${READER_BROWSER_PROFILE_DIR:-$VERIFY_DATA_DIR/browser/config}"
export READER_POSTGRES_DIR="${READER_POSTGRES_DIR:-$VERIFY_POSTGRES_VOLUME}"
export READER_APP_DATA_DIR="${READER_APP_DATA_DIR:-$VERIFY_DATA_DIR/app}"
export READER_SEMANTIC_SEARCH_ENABLED="$VERIFY_SEMANTIC_SEARCH_ENABLED"
export READER_VIDEO_DOWNLOAD_TIMEOUT_SECONDS="$VERIFY_VIDEO_DOWNLOAD_TIMEOUT_SECONDS"
export READER_ARCHIVE_TIMEOUT_SECONDS="$VERIFY_ARCHIVE_TIMEOUT_SECONDS"
export READER_BROWSER_LOAD_MAX_TIME_MS="$VERIFY_BROWSER_LOAD_MAX_TIME_MS"
export READER_BROWSER_CAPTURE_MAX_TIME_MS="$VERIFY_BROWSER_CAPTURE_MAX_TIME_MS"

mkdir -p "$READER_APP_DATA_DIR" "$READER_ARCHIVE_DIR" "$READER_BROWSER_PROFILE_DIR"

echo "==> Resetting verification Docker project"
docker_compose down -v --remove-orphans >/dev/null 2>&1 || true

if [ "$SKIP_BUILD" = "true" ]; then
  echo "==> Skipping Docker image build"
else
  echo "==> Building Docker image"
  docker_compose build "$SERVICE"
fi

echo "==> Starting PostgreSQL"
docker_compose up -d db

echo "==> Restarting Docker containers"
docker_compose up -d db "$SERVICE"

echo "==> Waiting for API health"
for attempt in $(seq 1 60); do
  if docker_compose exec -T "$SERVICE" curl -fsS "$HEALTH_URL" >/dev/null; then
    break
  fi
  if [ "$attempt" -eq 60 ]; then
    echo "API health check failed: $HEALTH_URL" >&2
    exit 1
  fi
  sleep 2
done

echo "==> Checking Chrome remote debugging endpoint"
docker_compose exec -T "$SERVICE" bash -lc '
url="${READER_BROWSER_REMOTE_DEBUGGING_URL:-http://127.0.0.1:9222}"
for attempt in $(seq 1 60); do
  if curl -fsS "$url/json/version" >/dev/null; then
    exit 0
  fi
  sleep 2
done
echo "Chrome remote debugging check failed: $url/json/version" >&2
exit 1
'

echo "==> Installing test dependencies inside the running container"
docker_compose exec -T "$SERVICE" \
  env -u VIRTUAL_ENV UV_COMPILE_BYTECODE=0 UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
  bash -lc "cd /app/backend && uv sync --locked --extra test --no-install-project"

echo "==> Copying tests into the running container"
docker_compose exec -T "$SERVICE" rm -rf /app/backend/tests
docker_compose cp backend/tests "$SERVICE":/app/backend/tests

TEST_DATABASE_URL="${READER_TEST_DATABASE_URL:-$(docker_compose exec -T "$SERVICE" printenv READER_DATABASE_URL)}"

echo "==> Running backend tests inside Docker"
docker_compose exec -T "$SERVICE" \
  env READER_TEST_DATABASE_URL="$TEST_DATABASE_URL" \
      READER_BOOTSTRAP_ADMIN_USERNAME=admin \
      READER_BOOTSTRAP_ADMIN_PASSWORD=change-me \
      READER_SEMANTIC_SEARCH_ENABLED=false \
  bash -lc "cd /app/backend && /app/backend/.venv/bin/python -m pytest"

echo "==> Generating frontend client inside Docker"
docker_compose exec -T "$SERVICE" \
  bash -lc "cd /app/frontend && bun run generate-client"

echo "==> Ensuring smoke test admin user inside Docker"
docker_compose exec -T "$SERVICE" \
  env READER_SMOKE_USERNAME="$USERNAME" \
      READER_SMOKE_PASSWORD="$PASSWORD" \
  bash -lc 'cd /app/backend && /app/backend/.venv/bin/python -m scripts.ensure_smoke_user --username "$READER_SMOKE_USERNAME" --password "$READER_SMOKE_PASSWORD"'

echo "==> Running frontend checks inside Docker"
docker_compose exec -T "$SERVICE" \
  bash -lc "cd /app/frontend && bun run check && bun run lint && bun run build"

echo "==> Running frontend unit tests inside Docker"
docker_compose exec -T "$SERVICE" \
  bash -lc "cd /app/frontend && bun run test"

if [ "$VERIFY_SEMANTIC_SEARCH_ENABLED" = "false" ]; then
  echo "==> Restoring semantic search in the running Docker service"
  READER_SEMANTIC_SEARCH_ENABLED=true \
    READER_VIDEO_DOWNLOAD_TIMEOUT_SECONDS="$RESTORE_VIDEO_DOWNLOAD_TIMEOUT_SECONDS" \
    READER_ARCHIVE_TIMEOUT_SECONDS="$RESTORE_ARCHIVE_TIMEOUT_SECONDS" \
    READER_BROWSER_LOAD_MAX_TIME_MS="$RESTORE_BROWSER_LOAD_MAX_TIME_MS" \
    READER_BROWSER_CAPTURE_MAX_TIME_MS="$RESTORE_BROWSER_CAPTURE_MAX_TIME_MS" \
    docker_compose up -d db "$SERVICE"
  echo "==> Waiting for restored API health"
  for attempt in $(seq 1 60); do
    if docker_compose exec -T "$SERVICE" curl -fsS "$HEALTH_URL" >/dev/null; then
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
