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
# Fonts for sharp/librsvg SVG text rasterization: the beta detect wizard draws
# numbered marker badges onto page renders, and a fontless slim image renders
# SVG <text> as blank — the model then can't see the marker numbers.
RUN apt-get update \
  && apt-get install -y --no-install-recommends fonts-dejavu-core fontconfig \
  && rm -rf /var/lib/apt/lists/*
COPY --from=build /out .
CMD ["node", "dist/index.js"]
