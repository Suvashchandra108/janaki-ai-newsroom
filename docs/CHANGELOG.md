# Changelog

## [0.1.0] — 2026-11-14 — Phase 0 and Phase 1

### Phase 0 — audit and plan
- Audit: no existing repository, starter ZIPs or schema found; greenfield build.
- Architecture (modular monolith + workers), database design and ERD, STRIDE threat model, roadmap, testing and deployment strategy, initial cost model.
- Plan change: daily generation cap (default 10 events/day) because the cost model shows full processing of ~100 items/day exceeds the ₹5–8k budget.

### Phase 1 — SaaS foundation
- Tenants, users (human/service, platform admins), system roles and permission catalogue.
- Login with tenant slug, Argon2id passwords, account lockout, 15-min JWT access tokens, rotating refresh tokens with reuse detection, logout / logout everywhere, password change.
- TOTP MFA, mandatory for tenant and platform admins, with replay protection and encrypted secrets.
- Human-only permissions (`articles.approve`, `articles.publish`) enforced for service accounts and API keys.
- API keys: HMAC-hashed, scoped, expiring, rotatable, revocable.
- PostgreSQL row-level security on all tenant tables; separate owner and non-bypass app roles.
- Append-only audit log at the database-grant level.
- Alembic migration `0001`, bootstrap scripts, Dockerfile, docker-compose, `.env.example`, OpenAPI export.
- 51 tests against PostgreSQL (97% coverage); ruff and mypy clean.

### Fixed
- RLS bypass scope was closed before pending ORM writes were flushed, silently dropping updates.
