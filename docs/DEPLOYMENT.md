# Deployment

Status: development stack defined; production deployment is Phase 9. Nothing here has been deployed yet.

## Environments

| Environment | Purpose | Data |
|---|---|---|
| Local development | `docker compose up` or native Python | Synthetic |
| Automated testing | CI runs `pytest`, `ruff`, `mypy`, `alembic check`, `pip-audit` | Ephemeral DB |
| Staging | Full stack on the VPS under a separate compose project and database; Janaki TV migration rehearsals | Copy of production content (no secrets) |
| Production | India-region VPS | Live |

## Local development

```bash
cp .env.example .env            # fill in every value
docker compose up --build       # postgres, redis, migrate, api
docker compose exec api python -m scripts.bootstrap platform-admin --email you@example.com --name "You"
docker compose exec api python -m scripts.bootstrap tenant --slug janaki-tv \
  --name "Janaki Television" --admin-email admin@janakitv.example.com --admin-name "Admin"
open http://localhost:8000/api/docs
```

Without Docker: start PostgreSQL 16 and Redis, create the roles from TESTING.md, then
`cd backend && alembic upgrade head && uvicorn app.main:app --reload`.

## Production: one Hetzner server (decision 15 Nov 2026)

The newsroom runs on its **own** small server, separate from the website (the website is on AWS EC2 `janaki-tv-1` in Mumbai, which has only 2 GB of memory). Everything is in `deploy/`: `docker-compose.prod.yml` (Postgres, Redis, API, worker, scheduler, dashboard, Caddy), `install.sh`, `connect-website.sh`, `update.sh`, `backup.sh`. Only ports 22, 80 and 443 are open; the API, database and Redis are not reachable from the internet. CI job `deploy-smoke` builds these images and starts this exact stack on every push.

**1. Server (owner, Hetzner console).** Cloud → New server: location *Falkenstein* or *Helsinki*, image **Ubuntu 24.04**, type **CX23** (2 vCPU, 4 GB), add your SSH key (or use the root password Hetzner emails), name `janaki-newsroom`. Note its IPv4 address.

**2. DNS (owner, Namecheap).** Domain List → janakitelevision.com → Advanced DNS → Add new record: **A Record**, Host `newsroom`, Value = the server's IPv4, TTL Automatic. Leave every other record alone.

**3. Install (on the server).**
```bash
ssh root@SERVER-IP
git clone https://github.com/Suvashchandra108/janaki-ai-newsroom.git && cd janaki-ai-newsroom
bash deploy/install.sh
```
It asks for: the dashboard address (Enter for `newsroom.janakitelevision.com`), the Gemini key (hidden), your email, name and an administrator password. It generates every other secret into `deploy/.env.production` — copy that file into your password manager (`cat deploy/.env.production`). The repository is private: when `git clone` asks, sign in with your GitHub user name and a [personal access token](https://github.com/settings/tokens) (read-only, this repo).

**4. First sign-in.** Open `https://newsroom.janakitelevision.com`, organisation `janaki-tv`. As administrator you must set up two-factor sign-in first (authenticator app).

**5. Website side** (after JanakiTelevision PR #1 is merged and the website updated with `deploy/update.sh` on its server): website admin → Administration → **Integrations** → Create “AI newsroom”, tick *Enable API key*, save, copy the key, tick *Active*, save.

**6. Connect (on the newsroom server).** `bash deploy/connect-website.sh` — paste the key at the hidden prompt. Automatic hourly delivery is **on** (owner's choice); drafts always arrive unpublished. `--manual` turns automatic delivery off.

**Updating:** `cd ~/janaki-ai-newsroom && bash deploy/update.sh` (backs up first). **Backups:** nightly at 03:20, last 14 database dumps and 4 weekly photo archives in `backups/`; copy them off the server now and then: `scp root@SERVER-IP:janaki-ai-newsroom/backups/newsroom-*.dump .`

## Dashboard (Phase 6)

`docker compose up dashboard` serves it on port 3100 (`NEWSROOM_API_URL=http://api:8000`). Put it behind HTTPS: its session cookies are `Secure`. Only for local testing over plain http set `COOKIE_SECURE=false`. Without Docker: `cd frontend && pnpm install && pnpm build && NEWSROOM_API_URL=… pnpm start`.

## Connecting the JanakiTelevision website (Phase 7)

1. On the website (after JanakiTelevision PR #1 is merged and deployed, and `pnpm migrate` has run): Administration → Integrations → Create “AI newsroom”, tick *Enable API key*, save, copy the key.
2. On the newsroom server (the key is read from a hidden prompt, never typed on the command line):
   ```bash
   docker compose exec api python -m scripts.bootstrap cms-connect --tenant janaki-tv --url https://janakitelevision.com
   ```
   It saves the key encrypted and reports whether the website accepted it.
3. Tick *Active* on the integration in the website admin, then `POST /api/v1/cms/connection/check` (or re-run step 2).
4. Optional: add `--auto` to deliver new drafts every hour (off by default). Without it, editors deliver per article with `POST /api/v1/articles/{id}/deliver`.

To stop deliveries at once: untick *Active* on the website (the key stops working), or set `enabled=false` with `PUT /cms/connection`.

## Production target (Phase 9 plan)

- One India-region VPS (4 vCPU / 8 GB to start). Ubuntu LTS, unattended security upgrades, SSH keys only, `ufw` allowing 22/80/443.
- Caddy reverse proxy (automatic TLS) → API container on a private Docker network; Postgres and Redis not exposed publicly.
- Outbound firewall for worker containers: only 80/443, and the SSRF gateway in-process.
- Secrets in a root-only `.env` (later: a secrets manager). Startup refuses default secrets.
- Migrations run as `janaki_owner` in a one-shot `migrate` container; the API uses `janaki_app`.
- Backups: nightly `pg_dump` encrypted with `age` and shipped to S3-compatible storage outside the VPS; 14 daily + 8 weekly retained; monthly restore test into staging, recorded in the changelog.
- Monitoring: `/health` and `/ready` probes, Sentry-compatible error reporting, container logs shipped off-host.
- Janaki TV's current website stays in production until a tested migration is approved by a human (see EDITORIAL_WORKFLOW.md and Phase 7).
