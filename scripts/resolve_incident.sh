#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(git branch --show-current)" != "main" ]]; then
  git checkout main
fi

MERGE_COMMIT="$(git log main --merges --first-parent --format=%H --grep='merge incident: n-plus-one' -n 1)"
if [[ -z "$MERGE_COMMIT" ]]; then
  echo "No n-plus-one incident merge was found on main." >&2
  exit 1
fi

git revert -m 1 --no-edit "$MERGE_COMMIT"
docker compose -f demo-stack/docker-compose.yml up -d --build --force-recreate orders loadgen
echo "Incident reverted and the orders service redeployed."

