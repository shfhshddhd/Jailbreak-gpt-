#!/usr/bin/env bash
set -uo pipefail

echo "Starting Telegram bot runner..."

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN secret is missing."
  exit 1
fi
if [[ -z "${GH_TOKEN:-}" || -z "${GITHUB_REPOSITORY:-}" ]]; then
  echo "ERROR: GH_TOKEN or GITHUB_REPOSITORY is missing."
  exit 1
fi

python3 -m pip install --disable-pip-version-check -r requirements.txt || exit 1
python3 -m py_compile main.py || {
  echo "ERROR: main.py has a syntax error; refusing to start or auto-restart."
  exit 1
}

# Leave margin before the GitHub-hosted runner's six-hour job limit.
echo "Bot will run for at most 5h 50m."
timeout --signal=TERM --kill-after=30s 21000s python3 -u main.py
BOT_STATUS=$?

if [[ "$BOT_STATUS" -ne 124 && "$BOT_STATUS" -ne 137 ]]; then
  echo "Bot exited unexpectedly (status $BOT_STATUS); not dispatching a restart."
  exit "$BOT_STATUS"
fi

echo "Runtime window reached. Requesting the next workflow run..."
HTTP_STATUS=$(curl --silent --show-error --output /tmp/dispatch-response.txt \
  --write-out "%{http_code}" \
  --request POST \
  --header "Authorization: Bearer ${GH_TOKEN}" \
  --header "Accept: application/vnd.github+json" \
  --header "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/${GITHUB_REPOSITORY}/dispatches" \
  --data '{"event_type":"restart_evil_bot"}') || {
    cat /tmp/dispatch-response.txt 2>/dev/null || true
    exit 1
  }

if [[ "$HTTP_STATUS" != "204" ]]; then
  echo "ERROR: GitHub dispatch failed (HTTP $HTTP_STATUS)."
  cat /tmp/dispatch-response.txt
  exit 1
fi

echo "Next workflow dispatch request accepted."
