#!/usr/bin/env bash
# Cron entry point, run every hour (crontab: `0 * * * *`).
#
#   report mode (00, 08, 16 UTC): full cycle with Telegram and a dated report copy, then
#                                 commit and push reports/ to GitHub.
#   hourly mode (other hours):    store the snapshot and refresh reports/latest.* only;
#                                 no Telegram, no git.
#
# Both modes then rebuild the dashboard data (web/data) and deploy it to Vercel from this
# server (scheduler/deploy_site.sh), so the site is at most an hour old without an hourly
# git commit. Pass --report or --hourly to force a mode.
# Writes its own log (logs/cron.log), so the crontab line needs no redirect.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
exec >>logs/cron.log 2>&1

REPORT_HOURS=" 00 08 16 "
mode=hourly
case "${1:-}" in
  --report) mode=report ;;
  --hourly) mode=hourly ;;
  "") [[ "$REPORT_HOURS" == *" $(date -u +%H) "* ]] && mode=report ;;
  *) echo "usage: $0 [--report|--hourly]"; exit 2 ;;
esac
echo "=== $(date -u +%FT%TZ) run start ($mode)"

exec 9>logs/run.lock
if ! flock -n 9; then
  echo "another run is in progress, skipping this one"
  exit 3
fi
export PERP_MONITOR_LOCK_HELD=1

if [ "$mode" = report ]; then
  ./run.sh
else
  ./run.sh --no-notify --no-archive >/dev/null
fi
status=$?
if [ "$status" -eq 2 ]; then
  echo "run aborted (exit 2), nothing to publish"
  exit 2
fi

# Dashboard: data first, then deploy. A failure here never blocks the report push.
.venv/bin/python -m perp_monitor site
site_status=$?
if [ "$site_status" -ne 0 ]; then
  echo "site export failed (exit $site_status); deploying whatever web/data holds"
fi
if ! ./scheduler/deploy_site.sh; then
  echo "dashboard deploy failed; the site keeps the previous deployment"
  [ "$status" -eq 0 ] && status=5
fi

if [ "$mode" = hourly ]; then
  echo "=== $(date -u +%FT%TZ) run end (exit $status)"
  exit "$status"
fi

if [ -n "$(git status --porcelain -- reports)" ]; then
  git add -- reports
  if ! git commit -q -m "data: report $(date -u +%Y-%m-%dT%H%MZ)" -- reports; then
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
