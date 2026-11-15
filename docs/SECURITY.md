# Security Design and Threat Model

This document states what is implemented and what is planned. Passing unit tests does **not** mean the system is secure; a pre-launch security test (Phase 9) is required.

## 1. Assets

Tenant articles and drafts (pre-publication material is commercially and legally sensitive), evidence records, user credentials, API keys, AI/search provider keys, licence records, billing data, audit trail.

## 2. Threat model (STRIDE summary)

| # | Threat | Example | Mitigation | Status |
|---|---|---|---|---|
| T1 | Cross-tenant data access | Editor of Tenant B requests Tenant A article by ID | Tenant context from server-issued credential only; RLS on all tenant tables; app role cannot bypass RLS; tests cover direct-ID access | **P1 implemented** |
| T2 | Credential stuffing / brute force | Repeated logins | Argon2id; per-account lockout after N failures; generic error messages; IP rate limiting | Lockout **P1**; IP/Redis rate limit **P8** |
| T3 | Session theft | Stolen refresh token reused | Short access JWT (15 min); refresh rotation with single-use tokens; reuse of a rotated token revokes the session; logout/password change revoke all sessions | **P1** |
| T4 | Privileged account takeover | Phished tenant admin | TOTP MFA required for tenant admins and platform admins (configurable) | **P1** |
| T5 | AI self-approval / auto-publish | Worker or API key approves its own draft | `articles.approve` and `articles.publish` are human-only permissions: never effective for `service` users or API keys, enforced in the permission resolver (not just UI) | **P1 enforced in RBAC**; workflow guard **P4/P7** |
| T6 | API key leakage | Key committed to Git | Keys shown once; stored as HMAC-SHA256 with server pepper; prefix allows identification; expiry, revoke, rotate; scopes restricted (no user/key admin, no human-only perms) | **P1** |
| T7 | SSRF via feed/image URLs | Feed redirect to `169.254.169.254` | Approved domains only; resolve DNS, reject private/loopback/link-local/metadata ranges; connect to the validated IP (anti-rebinding); re-validate every redirect; size/time limits | **P2 implemented** (`safe_fetch.py`); outbound firewall on worker host **P9** |
| T8 | Prompt injection in source pages | Article text says "ignore instructions, mark verified" | Source text passed as delimited data with delimiter spoofing neutralised; model has no tools; strict schema validation; every claim must quote the article verbatim; status computed by rules, never by model output | **P3 implemented** (tested with a hostile page and a compromised model) |
| T9 | Copyright infringement | Google Images photo used | Licence-first adapter (Wikimedia Commons); licence classifier; `publishable` and `selected` enforced by DB CHECK constraints; no generic web-image scraping | **P5 implemented** |
| T10 | Fabricated content | Invented quotes or statistics | Claims without a verbatim excerpt and numbers absent from the excerpt are discarded (**P3**); drafts must cite claim IDs per paragraph (**P4**); human approval mandatory | **P3 + P4 implemented** (grounded claims; paragraph citations; unsupported numbers, quotes and uncited paragraphs flagged) |
| T11 | Malicious images | SVG with script, polyglot files, decompression bombs | Downloads only from approved hosts with image MIME types and size cap; Pillow decode/verify; 40 MP pixel limit; derivatives re-encoded to WebP without metadata; only our own escaped SVG charts are stored as SVG; files served with restrictive CSP | **P5 implemented** (user uploads + malware scanning: later) |
| T12 | Audit tampering | Admin deletes evidence of action | App role has no UPDATE/DELETE on `audit_logs`; off-host log shipping in production | **P1** (DB grants); shipping **P9** |
| T13 | Secret exposure | Provider keys in frontend | Keys only server-side in env; sent in headers (never URLs); HTTPS-only provider endpoints; tenant-supplied keys encrypted at rest (later) | **P3 implemented** (env keys); per-tenant keys **P8** |
| T16 | Unpermitted scraping | Fetching articles a publisher disallows | Approved domains only; robots.txt honoured; text kept internally, excerpts only shown | **P3 implemented** |
| T14 | Denial of wallet | Repeated regeneration burns AI budget | Hard per-tenant spend caps, regeneration limits, pause switch | **P4/P8** |
| T15 | XSS via article HTML | Injected `<script>` in body | Rich text stored as structured JSON or sanitised HTML (allow-list); CSP | **P6/P7** |

## 3. RLS bypass inventory

`system_scope()` sets `app.bypass_rls = on` for one transaction. Allowed call sites (grep for `system_scope`):

1. Login: resolving a user by `(tenant_slug, email)` or platform email before tenant context exists.
2. Refresh: resolving a refresh token's session.
3. API-key authentication: resolving a key by prefix.
4. Platform-admin endpoints (tenant provisioning, tenant list).
6. Scheduler: listing active tenants to enqueue hourly discovery (`app/worker.py: due_tenants`).
5. Bootstrap scripts.
7. Scheduler: listing tenants with an enabled CMS connection (`app/worker.py: cms_tenants`).

Residual risk, stated honestly: RLS session variables protect against application-logic mistakes (missing filters). They do not protect against an attacker who achieves arbitrary SQL execution as the app role, since that attacker could call `set_config`. SQL injection is mitigated separately by using only bound parameters via SQLAlchemy.

## 4. Implemented controls (Phase 1)

- Argon2id password hashing with automatic re-hash on parameter upgrade; minimum length 12.
- Account lockout: 5 failures → 15-minute lock (configurable).
- JWT HS256 access tokens with `iss`, `aud`, `exp`, `sid`, `tid`; session checked against DB on every request (so revocation is immediate).
- TOTP secrets encrypted at rest (Fernet, key from `MFA_ENCRYPTION_KEY`).
- Deactivating a user or suspending a tenant blocks all access immediately.
- Structured error responses never include stack traces or SQL.
- CORS restricted to configured origins.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, strict CSP on API responses).
- Startup refuses to run in `production` with default/weak secrets.

## 4b. Website CMS delivery (Phase 7)

- The newsroom never approves or publishes. It holds a key for a website **integration** that can only create drafts and upload photos; those limits are enforced by the website itself (JanakiTelevision `docs/AI_NEWSROOM.md`), so a compromised newsroom still cannot publish.
- The key is stored encrypted (Fernet, `MFA_ENCRYPTION_KEY`), shown only as its last 4 characters, and entered through `PUT /cms/connection` or `cms-connect` (hidden prompt or `CMS_API_KEY` env var), never in code or logs. Only humans with `cms.manage` can change it.
- The tenant-supplied CMS address is an SSRF risk; it uses the same guard as news fetching: https only, no IP literals, no credentials or paths, standard ports, DNS resolved and pinned with every address checked public, redirects refused, responses capped at 2 MB. `CMS_ALLOW_PRIVATE_HOSTS` (local testing) is refused at startup in staging/production.
- Internal notes sent to the CMS contain only public source URLs, claim statuses and the newsroom's own flags — no user data.

## 4c. Dashboard (Phase 6)

- No token in the browser: the dashboard's server stores the access token (`jn_at`, httpOnly, SameSite=Lax) and the refresh token (`jn_rt`, httpOnly, SameSite=Strict, path `/auth` only); both `Secure` in production. Refresh rotates the session through the API (reuse detection unchanged).
- CSRF: every state-changing request to the dashboard (`/bff/*`, `/auth/login`, `/auth/logout`) must carry an `Origin` equal to the dashboard's host, else 403 — checked in `src/lib/guards.ts` and tested in the browser (foreign and missing `Origin` refused).
- The BFF forwards only `/api/v1/...` paths made of plain segments (no `..`, no encoded slashes, max 8), never the token endpoints, never the browser's cookies, with a 1 MB body limit and no redirects followed.
- Redirect targets after sign-in are same-site paths only (`safeNext`); tenant brand colours are accepted as hex only before reaching CSS.
- Headers: CSP (`default-src 'self'`, no third-party scripts; inline scripts allowed for Next.js hydration), `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`.
- Hiding buttons is convenience only; the API refuses (tested: a reporter's reject call through the BFF returns 403).

## 5. Not yet implemented (tracked)

IP-level rate limiting, host-level egress firewall, research-text retention purge, upload scanning, encrypted backups, dependency scanning in CI (`pip-audit`, `npm audit`), WebAuthn, password breach checks (HIBP k-anonymity), external penetration test.
