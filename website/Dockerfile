# detectkit website — static build served by nginx.
# Build context MUST be the repo root (the site imports ../docs + ../CHANGELOG.md):
#   docker build -f website/Dockerfile -t detectkit-web .

# ---- build ----
FROM node:22-alpine AS build
WORKDIR /app/website
COPY website/package.json website/package-lock.json ./
RUN npm ci
WORKDIR /app
# Doc sources (kept as the single source of truth; imported by scripts/sync-docs.mjs)
COPY docs ./docs
COPY CHANGELOG.md ./CHANGELOG.md
# Site sources (no node_modules / dist — keeps the layer slim and cacheable)
COPY website/astro.config.mjs website/tsconfig.json ./website/
COPY website/scripts ./website/scripts
COPY website/src ./website/src
COPY website/public ./website/public
WORKDIR /app/website
RUN npm run build

# ---- serve ----
FROM nginx:alpine
COPY website/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/website/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1
