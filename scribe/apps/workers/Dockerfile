# Build context must be the scribe/ monorepo root (Railway: service root
# directory = scribe, dockerfilePath = apps/workers/Dockerfile).
FROM node:22-slim AS build
WORKDIR /app
RUN corepack enable
COPY . .
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @scribe/workers... build
RUN pnpm --filter @scribe/workers --prod deploy --legacy /out

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /out .
CMD ["node", "dist/index.js"]
