#!/bin/bash
# pi/deploy.sh
# Deploys Pi code to the robot via rsync (skips unchanged files).
# Usage: ./pi/deploy.sh [--dry-run]

# ─── CONFIG ───────────────────────────────────────────────────────────────────
ROBOT_HOST="greg@robot"
REMOTE_DIR="~/"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)/"  # pi/ directory
# ──────────────────────────────────────────────────────────────────────────────

DRY_RUN=""
[[ "$1" == "--dry-run" ]] && DRY_RUN="--dry-run" && echo "🔍 Dry run — no files will be transferred"

echo "🤖 Deploying Pi code to ${ROBOT_HOST}:${REMOTE_DIR}"
echo "──────────────────────────────────────────────"

result=$(rsync \
  --checksum \
  --archive \
  --compress \
  --human-readable \
  --out-format="%f (%b transferred)" \
  --exclude="*.pyc" \
  --exclude="__pycache__/" \
  --exclude=".DS_Store" \
  --exclude="deploy.sh" \
  $DRY_RUN \
  "$LOCAL_DIR" \
  "${ROBOT_HOST}:${REMOTE_DIR}" 2>&1)

if [ $? -ne 0 ]; then
  echo "❌ Deploy failed — is the robot online?"
  echo "$result"
  exit 1
fi

UPLOADED=$(echo "$result" | grep "transferred" | wc -l | tr -d ' ')

if [ "$UPLOADED" -gt 0 ]; then
  echo "$result" | grep "transferred" | while read line; do
    echo "  📤 $line"
  done
  echo "──────────────────────────────────────────────"
  echo "✅ Deploy complete — ${UPLOADED} file(s) updated"
else
  echo "✔  Nothing to deploy — all files up to date"
fi
