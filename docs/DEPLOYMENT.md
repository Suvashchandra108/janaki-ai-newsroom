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

## Production target (Phase 9 plan)

- One India-region VPS (4 vCPU / 8 GB to start). Ubuntu LTS, unattended security upgrades, SSH keys only, `ufw` allowing 22/80/443.
- Caddy reverse proxy (automatic TLS) → API container on a private Docker network; Postgres and Redis not exposed publicly.
- Outbound firewall for worker containers: only 80/443, and the SSRF gateway in-process.
- Secrets in a root-only `.env` (later: a secrets manager). Startup refuses default secrets.
- Migrations run as `janaki_owner` in a one-shot `migrate` container; the API uses `janaki_app`.
- Backups: nightly `pg_dump` encrypted with `age` and shipped to S3-compatible storage outside the VPS; 14 daily + 8 weekly retained; monthly restore test into staging, recorded in the changelog.
- Monitoring: `/health` and `/ready` probes, Sentry-compatible error reporting, container logs shipped off-host.
- Janaki TV's current website stays in production until a tested migration is approved by a human (see EDITORIAL_WORKFLOW.md and Phase 7).
