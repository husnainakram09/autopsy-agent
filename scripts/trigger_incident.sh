#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(git branch --show-current)" != "main" ]]; then
  git checkout main
fi

git merge --no-ff incident/n-plus-one -m "merge incident: n-plus-one orders query"
docker compose -f demo-stack/docker-compose.yml up -d --build --force-recreate orders loadgen
echo "Incident deployed. Watch Grafana at http://localhost:3000."

