# Newsroom dashboard (Phase 6)

Next.js 16 + TypeScript + Tailwind 4. English and Nepali interface. Editors review AI drafts here
and send them to the website CMS, where people publish.

## How it talks to the API

The browser never holds an API token. Sign-in posts to the dashboard's own server
(`/auth/login`), which calls the newsroom API and stores the access and refresh tokens in
**httpOnly** cookies (`jn_at`: SameSite=Lax; `jn_rt`: SameSite=Strict, path `/auth` only).
Pages are server-rendered with the user's token (`src/lib/api.ts`). Buttons call `/bff/…`, a
same-origin proxy that adds the token, forwards only `/api/v1` paths with plain segments, and
refuses any state-changing request whose `Origin` is not the dashboard itself (CSRF).
Permissions are enforced by the API; hiding a button is only convenience.

## Run locally

```bash
pnpm install
NEWSROOM_API_URL=http://localhost:8000 pnpm dev          # http://localhost:3100
```

Production: `pnpm build && pnpm start` (standalone server). Over plain http on your own machine
add `COOKIE_SECURE=false`; never on a public server.

## Checks

```bash
pnpm format:check && pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

Browser tests need the real API and a seeded **e2e** database (they wipe it):

```bash
cd ../backend
TEST_DATABASE_URL=postgresql+psycopg://janaki_app:app_dev_pw@localhost:5432/janaki_e2e \
TEST_DATABASE_OWNER_URL=postgresql+psycopg://janaki_owner:owner_dev_pw@localhost:5432/janaki_e2e \
python -m tests.e2e_seed > ../frontend/seed.json
# start the API on :8000 against that database, and the dashboard on :3100, then:
cd ../frontend && pnpm exec playwright test      # CHROME_PATH=… to use an installed browser
```

## Screens

Dashboard · News inbox · Story research (facts, evidence, verify, photos) · Article drafts ·
Draft review (language tabs, flags, cited facts with sources, edit, regenerate, reject, send to
website, photo and licence, SEO/social, revision history) · Jobs (failed jobs with reasons,
run/pause discovery) · Sources · Usage · Website CMS · Users · Settings.

Not here yet (later phases): infographics editor, categories, API-key management screen,
plans and billing.
