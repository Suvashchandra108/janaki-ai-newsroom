#!/usr/bin/env bash
# Updates the newsroom to the latest code. Run ON THE SERVER:
#   cd ~/janaki-ai-newsroom && bash deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
exec 9> /tmp/newsroom-update.lock
flock -n 9 || { echo "another update is running"; exit 0; }
C="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production"
git pull --ff-only && git log --oneline -1
bash deploy/backup.sh
$C build
$C run --rm migrate
$C up -d
sleep 10
$C ps --format 'table {{.Service}}\t{{.Status}}'
