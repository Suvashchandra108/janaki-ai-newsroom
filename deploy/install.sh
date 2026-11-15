#!/usr/bin/env bash
# First-time setup of the newsroom on a fresh Ubuntu 24.04 server. Run ON THE SERVER as root:
#   git clone https://github.com/Suvashchandra108/janaki-ai-newsroom.git && cd janaki-ai-newsroom
#   bash deploy/install.sh
# Safe to run again: it keeps an existing deploy/.env.production and never re-creates accounts.
set -euo pipefail
cd "$(dirname "$0")/.."
ENV=deploy/.env.production
C="docker compose -f deploy/docker-compose.prod.yml --env-file $ENV"

echo "=== 1/8 system: updates, firewall, swap ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git ufw > /dev/null
ufw allow OpenSSH > /dev/null && ufw allow 80/tcp > /dev/null && ufw allow 443/tcp > /dev/null
ufw --force enable > /dev/null
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile > /dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
free -h | head -2

echo "=== 2/8 Docker ==="
if ! command -v docker > /dev/null; then
  curl -fsSL https://get.docker.com | sh > /dev/null
fi
docker --version

echo "=== 3/8 settings and secrets ==="
if [ ! -f "$ENV" ]; then
  cp deploy/.env.production.example "$ENV"
  chmod 600 "$ENV"
  gen() { openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-48; }
  fernet=$(openssl rand -base64 32 | tr '+/' '-_')
  sed -i "s|^POSTGRES_SUPERUSER_PASSWORD=.*|POSTGRES_SUPERUSER_PASSWORD=$(gen)|;
          s|^DB_OWNER_PASSWORD=.*|DB_OWNER_PASSWORD=$(gen)|;
          s|^DB_APP_PASSWORD=.*|DB_APP_PASSWORD=$(gen)|;
          s|^JWT_SECRET=.*|JWT_SECRET=$(gen)|;
          s|^API_KEY_PEPPER=.*|API_KEY_PEPPER=$(gen)|;
          s|^MFA_ENCRYPTION_KEY=.*|MFA_ENCRYPTION_KEY=$fernet|" "$ENV"
  read -r -p "Dashboard address [newsroom.janakitelevision.com]: " domain
  domain=${domain:-newsroom.janakitelevision.com}
  sed -i "s|^NEWSROOM_DOMAIN=.*|NEWSROOM_DOMAIN=$domain|;
          s|^CORS_ORIGINS=.*|CORS_ORIGINS=[\"https://$domain\"]|" "$ENV"
  read -r -s -p "Gemini API key (hidden, paste and press Enter): " gkey; echo
  [ -n "$gkey" ] || { echo "No key given; add AI_API_KEY to $ENV later."; }
  sed -i "s|^AI_API_KEY=.*|AI_API_KEY=$gkey|" "$ENV"
  unset gkey
  echo "Created $ENV (secrets generated). Copy it to your password manager:  cat $ENV"
else
  echo "Keeping existing $ENV"
fi

echo "=== 4/8 building (about 5-10 minutes) ==="
$C build

echo "=== 5/8 database and services ==="
$C up -d postgres redis
$C run --rm migrate
$C up -d

echo "=== 6/8 organisation, administrator and news sources ==="
if ! $C exec -T postgres psql -U postgres -d janaki -tAc "SELECT 1 FROM tenants WHERE slug='janaki-tv'" | grep -q 1; then
  read -r -p "Your email for the newsroom administrator: " admin_email
  read -r -p "Your name: " admin_name
  echo "Choose the administrator password (at least 12 characters):"
  $C run --rm api python -m scripts.bootstrap tenant --slug janaki-tv --name "Janaki Television" \
    --language en --admin-email "$admin_email" --admin-name "$admin_name"
fi
$C run --rm -v "$PWD/deploy/feeds:/feeds:ro" api python -m scripts.bootstrap sources --tenant janaki-tv --file /feeds/approved.json

echo "=== 7/8 backups and self-repair ==="
mkdir -p backups
current=$(crontab -l 2>/dev/null || true)
if ! grep -q 'deploy/backup.sh' <<< "$current"; then
  printf '%s\n%s\n' "$current" "20 3 * * * cd $PWD && bash deploy/backup.sh >> backups/backup.log 2>&1" | sed '/^$/d' | crontab -
fi
crontab -l | grep -q 'deploy/backup.sh' && echo "nightly backup scheduled (03:20 server time)"

echo "=== 8/8 checks ==="
sleep 10
$C ps --format 'table {{.Service}}\t{{.Status}}'
$C exec -T api python -c "import urllib.request;print('API:', urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
domain=$(grep '^NEWSROOM_DOMAIN=' "$ENV" | cut -d= -f2)
echo
echo "Done. Next: point $domain at this server (Namecheap A record), then open https://$domain"
echo "Then connect the website:  bash deploy/connect-website.sh"
