#!/usr/bin/env bash
set -euo pipefail

REPO="jbburgess/bskybot-sjearthquakes"
WORKFLOW="run-mirror.yml"
REF="master"

timestamp() { date '+%Y-%m-%d %H:%M:%S %Z'; }

# Verify gh auth before attempting dispatch
if ! gh auth status >/dev/null 2>&1; then
  echo "[$(timestamp)] ERROR: gh CLI is not authenticated" >&2
  exit 1
fi

if gh workflow run "$WORKFLOW" --repo "$REPO" --ref "$REF"; then
  echo "[$(timestamp)] OK: dispatched $WORKFLOW on $REPO@$REF"
else
  echo "[$(timestamp)] ERROR: failed to dispatch $WORKFLOW" >&2
  exit 1
fi
