# Build context must be the scribe/ monorepo root (Railway: service root
# directory = scribe, dockerfilePath = apps/api/Dockerfile).
FROM node:22-slim AS build
WORKDIR /app
RUN corepack enable
COPY . .
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @scribe/api... build
RUN pnpm --filter @scribe/api --prod deploy --legacy /out

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /out .
EXPOSE 3001
CMD ["node", "dist/server.js"]
