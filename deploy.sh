#!/bin/bash
# deploy.sh
# Deploys changed files to humn.au via rsync (skips unchanged files).
# Usage: ./deploy.sh [--dry-run]

# ─── CONFIG ───────────────────────────────────────────────────────────────────
REMOTE_HOST="gsydm1063.siteground.biz"
REMOTE_PATH="www/humn.au/public_html/"
FILES=(
  "spec.html"
  "robot.html"
  "ht-logo.svg"
)
# ──────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DRY_RUN=""
[[ "$1" == "--dry-run" ]] && DRY_RUN="--dry-run" && echo "🔍 Dry run — no files will be uploaded"

echo "🚀 Deploying to ${REMOTE_HOST}:${REMOTE_PATH}"
echo "──────────────────────────────────────────────"

UPLOADED=0
SKIPPED=0

for file in "${FILES[@]}"; do
  local_path="${SCRIPT_DIR}/${file}"
  if [ ! -f "$local_path" ]; then
    echo "  ⚠️  Skipping ${file} — file not found"
    ((SKIPPED++))
    continue
  fi

  # rsync --checksum compares file checksums (not timestamps) so only
  # genuinely changed content triggers an upload.
  result=$(rsync \
    --checksum \
    --archive \
    --compress \
    --human-readable \
    --out-format="%f (%b transferred)" \
    $DRY_RUN \
    "$local_path" \
    "${REMOTE_HOST}:${REMOTE_PATH}" 2>&1)

  if echo "$result" | grep -q "transferred"; then
    echo "  📤 ${file} — uploaded"
    ((UPLOADED++))
  else
    echo "  ✔  ${file} — unchanged, skipped"
    ((SKIPPED++))
  fi
done

echo "──────────────────────────────────────────────"
if [ $UPLOADED -gt 0 ]; then
  echo "✅ Deploy complete — ${UPLOADED} uploaded, ${SKIPPED} skipped"
  echo "   https://humn.au/robot.html"
  echo "   https://humn.au/spec.html"
else
  echo "✔  Nothing to deploy — all files up to date"
fi
