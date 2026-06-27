#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${READER_SEMANTIC_EVAL_COMPOSE_FILE:-compose.semantic-eval.yaml}"
SERVICE="${READER_SEMANTIC_EVAL_SERVICE:-eval-archive-desktop}"
DB_SERVICE="${READER_SEMANTIC_EVAL_DB_SERVICE:-eval-db}"
BASE_URL="${READER_SEMANTIC_EVAL_BASE_URL:-http://127.0.0.1:8000}"
HEALTH_URL="${BASE_URL%/}/api/v1/health"

mkdir -p \
  .local_eval/reader-semantic/data/postgres \
  .local_eval/reader-semantic/data/app/archive \
  .local_eval/reader-semantic/data/browser/config \
  .local_eval/reader-semantic/data/archive \
  .local_eval/reader-semantic/results

echo "==> Building semantic evaluation image"
docker compose -f "$COMPOSE_FILE" build "$SERVICE"

echo "==> Starting semantic evaluation database"
docker compose -f "$COMPOSE_FILE" up -d "$DB_SERVICE"

echo "==> Ensuring semantic evaluation database exists"
for attempt in $(seq 1 30); do
  if docker compose -f "$COMPOSE_FILE" exec -T "$DB_SERVICE" pg_isready -U reader >/dev/null; then
    docker compose -f "$COMPOSE_FILE" exec -T "$DB_SERVICE" \
      sh -lc "createdb -U reader reader 2>/dev/null || true"
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "Semantic evaluation database did not become ready." >&2
    exit 1
  fi
  sleep 2
done

echo "==> Stopping semantic evaluation service before seeding"
docker compose -f "$COMPOSE_FILE" stop "$SERVICE" >/dev/null 2>&1 || true

echo "==> Migrating and seeding semantic evaluation data"
docker compose -f "$COMPOSE_FILE" run --rm --no-deps --entrypoint bash "$SERVICE" \
  -lc "cd /app/backend && /app/backend/.venv/bin/alembic upgrade head && /app/backend/.venv/bin/python -m scripts.semantic_eval seed"

echo "==> Starting semantic evaluation service"
docker compose -f "$COMPOSE_FILE" up -d "$SERVICE"

echo "==> Waiting for semantic evaluation API health"
for attempt in $(seq 1 60); do
  if docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" curl -fsS "$HEALTH_URL" >/dev/null; then
    break
  fi
  if [ "$attempt" -eq 60 ]; then
    echo "Semantic evaluation API health check failed: $HEALTH_URL" >&2
    exit 1
  fi
  sleep 2
done

echo "==> Running semantic evaluation queries"
docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
  env READER_EVAL_BASE_URL="$BASE_URL" \
      READER_EVAL_RESULTS_DIR=/app/eval-results \
      READER_EVAL_USERNAME=admin \
      READER_EVAL_PASSWORD=change-me \
  bash -lc "cd /app/backend && /app/backend/.venv/bin/python -m scripts.semantic_eval run"

echo "==> Semantic evaluation finished"
echo "==> Report: .local_eval/reader-semantic/results/semantic-eval.md"
echo "==> JSON:   .local_eval/reader-semantic/results/semantic-eval.json"
echo "==> Evaluation service is still running at http://127.0.0.1:38166/"
