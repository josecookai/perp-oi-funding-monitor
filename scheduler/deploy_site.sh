#!/usr/bin/env bash
# Build the dashboard from web/data on this server and deploy it to Vercel production.
# run_and_push.sh calls this every hour, so fresh data never needs a git commit.
# Needs a linked project (.vercel/project.json, from `vercel link`) and a logged-in CLI.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/node/bin:$PATH"

if [ ! -f .vercel/project.json ]; then
  echo "deploy_site: no .vercel/project.json; run \`vercel link\` first" >&2
  exit 1
fi

vercel pull --yes --environment=production >/dev/null 2>&1
vercel build --prod --yes >/dev/null 2>&1 || {
  echo "deploy_site: vercel build failed; rerun by hand to see the error" >&2
  exit 1
}
# Without a TTY the CLI prints JSON on stdout and the human summary on stderr.
summary=$(vercel deploy --prebuilt --prod --yes 2>&1 >/dev/null) || {
  echo "deploy_site: vercel deploy failed: $(echo "$summary" | tail -3)" >&2
  exit 1
}
echo "deploy_site: $(echo "$summary" | grep -E "Production|Aliased" | tr -s ' ' | paste -sd ';')"
