# Frontend: build the Vite SPA, then serve the static output with nginx.
# Build context is the repo root (see docker-compose.yml), so paths are client/*.
FROM node:20-alpine AS build

WORKDIR /app/client

# Install dependencies from the lockfile (cached layer)
COPY client/package.json client/package-lock.json ./
RUN npm ci

# Build with the public API base baked in. Empty string → same-origin /api,
# which is correct when served behind the nginx reverse proxy below.
COPY client/ ./
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

FROM nginx:alpine
COPY client/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/client/dist /usr/share/nginx/html
EXPOSE 80
