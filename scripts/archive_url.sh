#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: scripts/archive_url.sh <url> [output-file.html]" >&2
  exit 2
fi

url="$1"
output="${2:-archive-$(date +%Y%m%d-%H%M%S).html}"
profile_dir="data/browser/config/.config/singlefile-chrome"

case "$output" in
  /*|*../*|../*)
    echo "output file must be a simple filename under data/archive" >&2
    exit 2
    ;;
esac

if [ -L "$profile_dir/SingletonSocket" ] && [ ! -e "$profile_dir/SingletonSocket" ]; then
  rm -f "$profile_dir"/Singleton*
fi

docker compose exec -T -u abc archive-desktop \
  env DISPLAY=:1 HOME=/config \
  single-file "$url" "/config/Downloads/$output" \
  --browser-executable-path=/usr/bin/google-chrome \
  --browser-headless=false \
  --browser-arg=--user-data-dir=/config/.config/singlefile-chrome \
  --browser-arg=--no-sandbox \
  --browser-arg=--disable-dev-shm-usage \
  --browser-wait-delay=2000 \
  --filename-conflict-action=overwrite

echo "data/archive/$output"
