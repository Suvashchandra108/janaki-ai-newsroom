# Newsroom dashboard (Next.js standalone). Not yet built in CI: no Docker daemon was available
# when this was written; `docker compose build dashboard` locally.
FROM node:22-slim AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production PORT=3100 HOSTNAME=0.0.0.0
RUN useradd --system --uid 10001 dashboard
COPY --from=build --chown=dashboard /app/.next/standalone ./
USER dashboard
EXPOSE 3100
CMD ["node", "server.js"]
