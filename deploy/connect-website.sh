#!/usr/bin/env bash
# Connects the newsroom to the JanakiTelevision website CMS, with automatic hourly delivery of
# drafts (they always arrive UNPUBLISHED; an editor publishes). Run ON THE SERVER:
#   bash deploy/connect-website.sh            (asks for the integration key, hidden)
# Turn automatic delivery off again with:   bash deploy/connect-website.sh --manual
set -euo pipefail
cd "$(dirname "$0")/.."
C="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production"
auto="--auto"; [ "${1:-}" = "--manual" ] && auto=""
read -r -p "Website address [https://janakitelevision.com]: " url
url=${url:-https://janakitelevision.com}
read -r -s -p "Integration API key from the website admin (hidden): " key; echo
CMS_API_KEY="$key" $C run --rm -e CMS_API_KEY api python -m scripts.bootstrap cms-connect \
  --tenant janaki-tv --url "$url" $auto
unset key
