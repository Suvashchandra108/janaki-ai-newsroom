# API Documentation

Base path: `/api/v1`. Machine-readable spec: [`openapi.json`](openapi.json) (regenerate with the command in TESTING.md). Interactive docs at `/api/docs` outside production.

## Authentication

| Method | Header | Use |
|---|---|---|
| User session | `Authorization: Bearer <access_token>` | Dashboard users. 15-minute access token; renew with `/auth/refresh`. |
| API key | `X-API-Key: jnk_<prefix>_<secret>` | Tenant integrations. Scoped; cannot manage users/keys, approve or publish. |

The tenant is always derived from the credential. No endpoint accepts a tenant ID that changes whose data you see.

## Errors

```json
{ "error": { "code": "mfa_enrollment_required", "message": "Set up two-factor authentication to continue.", "request_id": "3f9c1a2b4d5e6f70", "details": {} } }
```

Common codes: `unauthorized`, `invalid_credentials`, `mfa_required`, `invalid_mfa_code`, `mfa_enrollment_required`, `forbidden`, `tenant_suspended`, `not_found` (also returned for other tenants' resources), `conflict`, `validation_error`, `weak_password`, `invalid_scope`, `internal_error`.

## Phase 1 endpoints (implemented)

| Method & path | Auth | Permission | Purpose |
|---|---|---|---|
| POST `/auth/login` | none | — | `{email, password, tenant_slug?, totp_code?}` → tokens. Omit `tenant_slug` only for platform admins. |
| POST `/auth/refresh` | none | — | Rotates refresh token. Replaying an old one revokes the session. |
| POST `/auth/logout` | user | — | `{everywhere: bool}` |
| GET `/auth/me` | user | — | Identity, permissions, `mfa_enrollment_required` |
| POST `/auth/password` | user | — | Change password; other sessions revoked |
| POST `/auth/mfa/setup` | user | — | Returns TOTP secret + `otpauth://` URI |
| POST `/auth/mfa/enable` | user | — | `{code}` confirms enrolment |
| POST `/tenants` | platform admin | `platform.tenants.manage` | Provision tenant + first tenant admin |
| GET `/tenants` | platform admin | `platform.tenants.manage` | List tenants |
| PATCH `/tenants/{id}` | platform admin | `platform.tenants.manage` | Rename / suspend / reactivate |
| GET `/tenants/current` | user or key | `tenant.read` | Own organisation |
| PATCH `/tenants/current` | user | `tenant.update` | Name, default language |
| GET `/users` | user or key | `users.read` | List users in own tenant |
| POST `/users` | user | `users.manage` | Create user (`kind`: human/service) with roles |
| GET `/users/{id}` | user or key | `users.read` | |
| PATCH `/users/{id}` | user | `users.manage` | Name, roles, activate/deactivate, `reset_mfa` |
| GET `/roles` | user or key | `users.read` | System roles and their permissions |
| GET `/api-keys` | user | `apikeys.manage` | List (secrets never returned) |
| POST `/api-keys` | user | `apikeys.manage` | `{name, scopes, expires_in_days}` → key shown once |
| POST `/api-keys/{id}/rotate` | user | `apikeys.manage` | New key, old revoked |
| DELETE `/api-keys/{id}` | user | `apikeys.manage` | Revoke |
| GET `/audit-logs` | user or key | `audit.read` | `?action=&limit=&offset=` |
| GET `/health`, `/ready` | none | — | Liveness / DB readiness (outside `/api/v1`) |

## Phase 2 endpoints (implemented)

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/sources` | `events.read` | Approved sources with last fetch status/error |
| POST `/sources` | `sources.manage` | Add RSS (`feed_url` must be on `allowed_domains`) or search source |
| GET / PATCH `/sources/{id}` | `events.read` / `sources.manage` | View / edit, enable/disable. No DELETE (traceability) |
| GET `/discovery/status` | `events.read` | Paused?, quota, items today, next run, last job |
| POST `/discovery/run` | `discovery.run` | Queue a run now (202). 409 if paused, 503 if queue down |
| POST `/discovery/pause`, `/discovery/resume` | `discovery.run` | Stop / restart scheduled discovery |
| GET `/discovery/jobs` | `events.read` | Job history with per-run results and errors |
| GET `/discovery/items` | `events.read` | Discovered items (`?source_id=`) |
| GET `/events` | `events.read` | Events (`?min_publishers=2` for multi-source stories) |
| GET `/events/{id}` | `events.read` | Event with every source item |

## Phase 3 endpoints (implemented)

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/events/{id}/claims` | `events.read` | Claims with status, reason, independent-source count and every piece of evidence (URL, publisher, dates, verbatim excerpt, supports/contradicts) |
| GET `/events/{id}/research` | `events.read` | Per-article retrieval status, claim status counts, last research job |
| POST `/events/{id}/research` | `discovery.run` | Queue research now (202) |
| GET `/claims/{id}` | `events.read` | One claim with evidence |
| POST `/claims/{id}/review` | `evidence.review`, **human user only** | `{verified: true, note}` marks editor-verified (note required); `{verified: false}` returns to the rule-based status |
| GET `/usage/ai?days=30` | `usage.read` | AI calls and tokens by task |

## Phase 4 endpoints (implemented)

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/articles?status=` | `articles.read` | Drafts with headline and warning count |
| GET `/articles/{id}` | `articles.read` | Current version (paragraphs with claim IDs, flags, SEO, social, attribution) and version list |
| GET `/articles/{id}/versions/{n}` | `articles.read` | Any earlier version |
| PATCH `/articles/{id}` | `articles.edit`, human only | Edit → new version, re-checked; claim IDs must belong to the event |
| POST `/articles/{id}/regenerate` | `articles.edit`, human only | New AI version; limited per tenant (429 when exhausted) |
| POST `/articles/{id}/reject` | `articles.reject`, human only | `{reason}` |
| GET `/events/{id}/articles` | `articles.read` | Articles for an event |
| POST `/events/{id}/write` | `articles.create` | Queue writing (409 if not eligible) |

There is no approve/publish endpoint: approval and publication happen in the website CMS.

Platform admins deliberately have **no** access to tenant newsroom data through tenant endpoints.

## Example

```bash
curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@janakitv.example.com","password":"…","tenant_slug":"janaki-tv","totp_code":"123456"}'
```

## Planned endpoint groups

`/media`, `/infographics` (P5) · `/notifications` (P6) · `/cms`, `/publishing` (P7) · `/usage`, `/subscriptions` (P8).
