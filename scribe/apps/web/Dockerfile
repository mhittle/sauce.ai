# Build context must be the scribe/ monorepo root (Railway: service root
# directory = scribe, dockerfilePath = apps/web/Dockerfile).
# VITE_API_URL must be set at BUILD time (Railway build-time env var).
FROM node:22-slim AS build
WORKDIR /app
RUN corepack enable
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
COPY . .
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @scribe/web... build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
RUN npm install -g sirv-cli@3
COPY --from=build /app/apps/web/dist ./dist
EXPOSE 8080
CMD ["sh", "-c", "sirv dist --single --host 0.0.0.0 --port ${PORT:-8080}"]
