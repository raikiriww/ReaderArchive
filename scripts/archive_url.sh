#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: scripts/archive_url.sh <url> [output-file.html]" >&2
  exit 2
fi

url="$1"
output="${2:-archive-$(date +%Y%m%d-%H%M%S).html}"
remote_debugging_url="${READER_BROWSER_REMOTE_DEBUGGING_URL:-http://127.0.0.1:9222}"

case "$output" in
  /*|*../*|../*)
    echo "output file must be a simple filename under data/archive" >&2
    exit 2
    ;;
esac

docker compose exec -T -u abc archive-desktop \
  env DISPLAY=:1 HOME=/config \
  single-file "$url" "/config/Downloads/$output" \
  --browser-server="$remote_debugging_url" \
  --browser-wait-until=networkIdle \
  --browser-wait-until-delay=0 \
  --browser-wait-until-fallback=false \
  --load-deferred-images=true \
  --load-deferred-images-dispatch-scroll-event=true \
  --load-deferred-images-max-idle-time=5000 \
  --remove-unused-styles=false \
  --remove-alternative-medias=false \
  --filename-conflict-action=overwrite

echo "data/archive/$output"
