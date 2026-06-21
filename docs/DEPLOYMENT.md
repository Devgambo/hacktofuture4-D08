# Deployment Plan — EasyOps CI/CD Agent (Docker Compose, self-host)

This plan deploys the full stack — **FastAPI/LangGraph backend**, **React/Vite
frontend**, and **PostgreSQL + pgvector** — with Docker Compose on a single host
(VPS or your own machine). It includes ready-to-paste `Dockerfile`s, a
`docker-compose.yml`, and an nginx reverse-proxy config.

> The repo currently has **no** Dockerfiles, compose file, or CI. The files
> below are the proposed artifacts to add. Paths are relative to the repo root.

Related: [`CODEBASE_OVERVIEW.md`](./CODEBASE_OVERVIEW.md),
[`BUGS_AND_IMPROVEMENTS.md`](./BUGS_AND_IMPROVEMENTS.md). Fix the **Critical**
items there (esp. C1–C3) before exposing this publicly.

---

## 1. Prerequisites

**Host:** Docker Engine + Docker Compose v2, a public DNS name with TLS
(Caddy/Traefik/nginx + Let's Encrypt), and inbound 80/443.

**External services to provision:**
| Service | Needed for | Notes |
| --- | --- | --- |
| OpenRouter account + API key | All LLM calls | `OPENROUTER_API_KEY` |
| GitHub OAuth App | Login + repo access | Set callback to `https://<domain>/api/auth/callback` |
| GitHub webhook secret | Verify webhook payloads | `GITHUB_WEBHOOK_SECRET` |
| PostgreSQL **with pgvector** | All persistence + memory | Compose ships `pgvector/pgvector`; or use **Neon** (already used in dev) |
| Public HTTPS URL | GitHub → webhooks | `WEBHOOK_BASE_URL`; use **ngrok** for local testing |
| Telegram bot *(optional)* | Notifications/approvals | `TELEGRAM_BOT_TOKEN`, allow-list |
| AWS / Azure / GCP creds *(optional)* | CD log access | Only if using CD monitoring |

---

## 2. Environment configuration

### Backend — `server/.env` (never commit; `.env` is gitignored)
Start from `server/.env.example`. Required for production:
```dotenv
APP_ENV=production
LOG_LEVEL=info

OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GITHUB_WEBHOOK_SECRET=...

# In compose, host is the postgres service name:
DATABASE_URL=postgresql://easyops:STRONGPASS@postgres:5432/easyops

# REQUIRED in production — generate once and keep stable:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEY=...

WEBHOOK_BASE_URL=https://<your-domain>
# Recommended (see BUGS C2): comma-separated allowed origins
CORS_ORIGINS=https://<your-domain>

# Optional integrations
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
TELEGRAM_WEBHOOK_URL=https://<your-domain>/api/webhooks/telegram
TELEGRAM_ALLOWED_USER_IDS=123456789
CD_WEBHOOK_SECRET=...
# AWS_*, AZURE_*, GCP_* only if CD monitoring is used
```

### Frontend — `client/.env.production`
The frontend must be built with the public API URL (see bug C1; wire
`import.meta.env.VITE_API_BASE` first):
```dotenv
VITE_API_BASE=https://<your-domain>
```
With the nginx reverse proxy below, you can instead set
`VITE_API_BASE=` (empty) and let same-origin `/api` calls flow through nginx.

---

## 3. Local development (no Docker)

```bash
# Backend
cd server
uv sync
uv run uvicorn main:app --reload --port 8000

# Frontend (new terminal)
cd client
npm install
npm run dev          # http://localhost:5173
```
A local Postgres with pgvector is required (or point `DATABASE_URL` at Neon).
Use ngrok to expose port 8000 so GitHub can reach your webhooks during dev.

---

## 4. Proposed Docker artifacts

### `server/Dockerfile`
```dockerfile
FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*
# uv for fast, locked installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev

COPY server/ ./
ENV PATH="/app/server/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `client/Dockerfile` (build → static, served by nginx)
```dockerfile
FROM node:20-alpine AS build
WORKDIR /app/client
COPY client/package*.json ./
RUN npm ci
COPY client/ ./
ARG VITE_API_BASE
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build      # outputs to /app/client/dist

FROM nginx:alpine
COPY client/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/client/dist /usr/share/nginx/html
EXPOSE 80
```

### `client/nginx.conf` (serves SPA + proxies API & SSE to backend)
```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API + auth → backend
    location /api/ {
        proxy_pass http://server:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Server-Sent Events: disable buffering, allow long-lived connections
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 24h;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }

    location /health {
        proxy_pass http://server:8000/health;
    }
}
```

### `docker-compose.yml` (repo root)
```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: easyops
      POSTGRES_PASSWORD: STRONGPASS
      POSTGRES_DB: easyops
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U easyops"]
      interval: 5s
      timeout: 5s
      retries: 10

  server:
    build:
      context: .
      dockerfile: server/Dockerfile
    env_file: server/.env
    depends_on:
      postgres:
        condition: service_healthy
    expose:
      - "8000"
    restart: unless-stopped

  client:
    build:
      context: .
      dockerfile: client/Dockerfile
      args:
        VITE_API_BASE: ""          # empty → same-origin /api via nginx
    depends_on:
      - server
    ports:
      - "80:80"
    restart: unless-stopped

volumes:
  pgdata:
```

> TLS: put Caddy/Traefik or host-nginx in front of the `client` service for
> Let's Encrypt, or add a `caddy` service mapping 443.

---

## 5. Build, run, initialize

```bash
# from repo root
docker compose build
docker compose up -d
docker compose logs -f server      # watch startup
```

**Database schema** is created automatically: `lifespan` in `main.py` calls
`rsi.db.init_db()`, which runs `server/rsi/schema.sql` (idempotent
`CREATE TABLE IF NOT EXISTS` + inline migrations). The `pgvector/pgvector` image
provides the `vector` extension required by `agent_memory`.

> No migration tool (Alembic) is in use. Schema changes today rely on editing
> `schema.sql`. Adopting Alembic is a recommended follow-up for safe upgrades.

---

## 6. Wire up GitHub & Telegram

1. **GitHub OAuth App** → Authorization callback URL: `https://<domain>/api/auth/callback`.
2. **GitHub webhook** (per repo or App): payload URL `https://<domain>/api/webhooks/github`,
   content type `application/json`, secret = `GITHUB_WEBHOOK_SECRET`, events:
   pushes, pull requests, check runs (+ installation if using a GitHub App).
   Note: the app can also self-register webhooks via `webhook_manager.py` /
   `POST /api/settings/webhook-url`.
3. **CD webhook (optional):** point your pipeline at
   `https://<domain>/api/webhooks/cd-failure` with `CD_WEBHOOK_SECRET`.
4. **Telegram (optional):** set the bot webhook to
   `https://<domain>/api/webhooks/telegram`.

---

## 7. Verify (smoke test)

```bash
curl -fsS https://<domain>/health           # → ok
```
Then in a browser:
1. Open `https://<domain>/` → click login → complete GitHub OAuth → land on `/init`.
2. Search a repo and **Initialize** it (builds the RSI; check `server` logs).
3. Open `/monitor` — confirm the SSE event stream connects (events appear live).
4. Trigger a webhook: open/push a PR on the monitored repo and watch a review
   job appear in `/monitor`; or `POST` a test payload to `/api/webhooks/cd-failure`.
5. Confirm rows land in Postgres:
   `docker compose exec postgres psql -U easyops -c "\dt"`.

---

## 8. Production hardening checklist

Do these before real traffic (details in `BUGS_AND_IMPROVEMENTS.md`):
- [ ] **C1** Build the frontend with a real `VITE_API_BASE` (or same-origin via nginx).
- [ ] **C2** Set `CORS_ORIGINS` to your domain (don't ship localhost).
- [ ] **C3** Set a stable `TOKEN_ENCRYPTION_KEY`; store it in a secrets manager.
- [ ] **C4** Externalize in-memory state (jobs/events/SSE/dedup → Postgres/Redis)
      before running more than one `server` replica.
- [ ] TLS everywhere; secure, HTTP-only session cookies.
- [ ] **H4** Rate limit + body-size cap on webhook endpoints; truncate CD logs.
- [ ] **H5** Eager DB init in `lifespan` + a real DB health check.
- [ ] Rotate any dev credentials that were ever shared; keep `.env` out of git.
- [ ] Log aggregation + structured logs (`structlog`) with correlation ids.
- [ ] Regular DB backups (`pg_dump` cron, or Neon's PITR if using Neon).
- [ ] Add `.github/workflows/` CI: lint, type-check, tests, image build/push.
- [ ] Adopt Alembic for versioned schema migrations.

---

## 9. Alternative: managed Postgres (Neon)

To skip the `postgres` container, drop it from compose and set
`DATABASE_URL` to your Neon connection string (enable the `vector` extension in
Neon). Everything else is unchanged.
