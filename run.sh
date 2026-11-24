#!/usr/bin/env bash
# One full cycle against live data: fetch, compare, write reports/, send Telegram.
#   ./run.sh                  scheduled-style run
#   ./run.sh --manual         ad-hoc run (marked "Manual run" in the report)
#   ./run.sh --no-store       dry run: print the report only
# Exit codes: 0 ok, 1 a venue or Telegram failed, 2 aborted, 3 another run holds the lock.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs
if [ "${PERP_MONITOR_LOCK_HELD:-0}" != "1" ]; then
  exec 9>logs/run.lock
  if ! flock -n 9; then
    echo "$(date -u +%FT%TZ) another run is in progress, not starting" >&2
    exit 3
  fi
fi
exec .venv/bin/python -m perp_monitor run "$@"
