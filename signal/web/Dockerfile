# sauce.ai/signal web — build the Vite SPA, serve it with nginx.
# Railway: deploy with Root Directory = signal/web; set VITE_API_BASE (the API
# service's public URL) as a variable so it's baked into the build.

FROM node:22-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci || npm install
COPY . .
# VITE_* must be present at BUILD time (Vite inlines them). Railway passes
# service variables as build args.
ARG VITE_API_BASE=""
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:1.27-alpine
# Railway provides $PORT at runtime; the nginx image envsubst's this template.
ENV PORT=8080
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
