#!/usr/bin/env bash
# Cron entry point: run one cycle, refresh the dashboard data, then commit and push.
# Each push to main redeploys the Vercel dashboard (root directory web/).
# Writes its own log (logs/cron.log), so the crontab line needs no redirect.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
exec >>logs/cron.log 2>&1
echo "=== $(date -u +%FT%TZ) run start"

exec 9>logs/run.lock
if ! flock -n 9; then
  echo "another run is in progress, skipping this one"
  exit 3
fi
export PERP_MONITOR_LOCK_HELD=1

./run.sh
status=$?
if [ "$status" -eq 2 ]; then
  echo "run aborted (exit 2), nothing to push"
  exit 2
fi

# Dashboard data (web/data): report copy, history and catalyst cards. A failure here
# never blocks the report push; the site keeps the previous cards and says so.
.venv/bin/python -m perp_monitor site
site_status=$?
if [ "$site_status" -ne 0 ]; then
  echo "site export failed (exit $site_status); pushing the report anyway"
fi

if [ -n "$(git status --porcelain -- reports web/data)" ]; then
  git add -- reports web/data
  if ! git commit -q -m "data: report $(date -u +%Y-%m-%dT%H%MZ)" -- reports web/data; then
    echo "git commit failed"
    exit 4
  fi
fi
if ! git fetch -q origin main; then
  echo "git fetch failed; local commits kept, will retry next run"
  exit 4
fi
if [ "$(git rev-list --count HEAD..origin/main)" -gt 0 ]; then
  if ! git rebase -q --autostash origin/main; then
    git rebase --abort 2>/dev/null || true
    echo "git rebase onto origin/main failed; local commits kept, will retry next run"
    exit 4
  fi
fi
if [ "$(git rev-list --count origin/main..HEAD)" -gt 0 ] && ! git push -q origin HEAD:main; then
  echo "git push failed; local commits kept, will retry next run"
  exit 4
fi
echo "=== $(date -u +%FT%TZ) run end (exit $status)"
exit "$status"
