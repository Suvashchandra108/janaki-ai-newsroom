# Janaki AI Newsroom

A multi-tenant, AI-assisted newsroom and CMS for newspapers, TV channels and digital portals. It discovers news, researches and cross-checks it, drafts two distinct editorial angles (English first; Nepali to follow), sources licensed visuals, and hands everything to human editors. **No AI process can approve or publish an article.**

First tenant: **Janaki Television**.

## Status

| Phase | | Status |
|---|---|---|
| 0 | Audit & engineering plan | ✅ done |
| 1 | SaaS foundation (tenants, auth, MFA, RBAC, API keys, RLS, audit) | ✅ done |
| 2 | News discovery & scheduling (RSS, SSRF-safe fetch, dedupe, clustering, hourly jobs) | ✅ done, verified in CI |
| 3 | Research & evidence (article retrieval, grounded AI claim extraction, rule-based corroboration, editor review) | ✅ done, awaiting review |
| 4 | English AI writing (two angles) | next |
| 5–9 | Visuals, dashboard, CMS integration, billing, production | planned |

**Language:** English-only at launch (decision 14 Nov 2026). Nepali will be enabled later per tenant.

Not production-ready. See [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md).

## Quick start (development)

```bash
cp .env.example .env              # fill in values
docker compose up --build        # postgres, redis, migrate, api, worker, beat
docker compose exec api python -m scripts.bootstrap platform-admin --email you@example.com --name "You"
docker compose exec api python -m scripts.bootstrap tenant --slug janaki-tv --name "Janaki Television" \
  --admin-email admin@janakitv.example.com --admin-name "Janaki Admin"
# API docs: http://localhost:8000/api/docs
```

Native Python and test instructions: [docs/TESTING.md](docs/TESTING.md).

## Repository layout

```
backend/   FastAPI modular monolith (app/), Alembic migrations, scripts, tests
frontend/  Next.js dashboard and public site (Phase 6–7)
deploy/    Infrastructure helpers (Postgres role init)
docs/      Architecture, schema, API, security, deployment, roadmap, testing,
           cost model, changelog, editorial workflow, image licensing policy
```

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Database schema](docs/DATABASE_SCHEMA.md) · [API](docs/API_DOCUMENTATION.md) · [Security](docs/SECURITY.md) · [Deployment](docs/DEPLOYMENT.md) · [Roadmap](docs/DEVELOPMENT_ROADMAP.md) · [Testing](docs/TESTING.md) · [Cost model](docs/COST_MODEL.md) · [Changelog](docs/CHANGELOG.md) · [Editorial workflow](docs/EDITORIAL_WORKFLOW.md) · [Image licensing](docs/IMAGE_LICENSING_POLICY.md)
