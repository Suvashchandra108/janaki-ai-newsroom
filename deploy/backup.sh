#!/usr/bin/env bash
# Database backup (checked readable), last 14 kept, plus photos weekly (Sundays), last 4 kept.
# Copy backups off the server now and then (see docs/DEPLOYMENT.md).
set -euo pipefail
cd "$(dirname "$0")/.."
C="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production"
mkdir -p backups
f="backups/newsroom-$(date -u +%Y%m%dT%H%M%SZ).dump"
$C exec -T postgres pg_dump -U postgres -Fc janaki > "$f"
$C exec -T postgres pg_restore --list < "$f" > /dev/null
echo "$(date -u +%FT%TZ) db backup OK: $f ($(du -h "$f" | cut -f1))"
ls -1t backups/newsroom-*.dump | tail -n +15 | xargs -r rm --
if [ "$(date -u +%u)" = "7" ] || [ "${1:-}" = "--media" ]; then
  m="backups/media-$(date -u +%Y%m%d).tar.gz"
  docker run --rm -v janaki-newsroom_media:/m:ro -v "$PWD/backups:/b" alpine tar czf "/b/$(basename "$m")" -C /m .
  echo "$(date -u +%FT%TZ) media backup OK: $m"
  ls -1t backups/media-*.tar.gz | tail -n +5 | xargs -r rm --
fi
