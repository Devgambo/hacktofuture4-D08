# Deployment Guide — Backend on AWS, Frontend on Vercel

Step-by-step guide to deploy **EasyOps CI/CD Agent** with:

- **Backend** (FastAPI + LangGraph) on an **AWS EC2** instance, in Docker, behind
  **Caddy** (automatic HTTPS).
- **Frontend** (React/Vite SPA) on **Vercel**.
- **Database** (PostgreSQL + pgvector) on **Neon** (recommended) or **AWS RDS**.

> Why EC2 and not Lambda/App Runner? The backend holds **in-process state**
> (job history, the live SSE event stream, a dedup set) and streams Server-Sent
> Events to the dashboard. It must run as a **single long-lived instance** (one
> worker, no autoscaling). A single small EC2 box is the simplest fit. ECS
> Fargate with `desiredCount: 1` also works (see §11).

---

## 0. Architecture & domains

```
   Browser
     │  app.example.com  (HTTPS)
     ▼
  Vercel  ── static SPA (Vite build) ─────────────┐
     │                                            │  fetch(credentials: include)
     │  VITE_API_BASE = https://api.example.com   │
     ▼                                            ▼
  api.example.com (HTTPS, Caddy on EC2) ──► FastAPI :8000 (Docker, 1 instance)
                                              │
                                              ├──► Neon / RDS Postgres (pgvector)
                                              ├──► OpenAI API
                                              ├──► GitHub API + MCP (npx, in-container)
                                              └──► Telegram (optional)
```

**Use a custom domain with two subdomains under one root** (e.g.
`app.example.com` for Vercel and `api.example.com` for AWS). They are then the
**same site**, so the session cookie works with `SameSite=Lax` and no extra
config. If instead you use the raw `*.vercel.app` host against the AWS box, they
are **cross-site** and you must set `COOKIE_SAMESITE=none` (covered in §8).

---

## 1. Prerequisites

- A **domain name** you control (for `api.` and `app.` subdomains).
- An **AWS account** and a **Vercel account** (free tier is fine).
- A **GitHub OAuth App** (created in §6).
- An **OpenAI API key** (used for LLM calls + embeddings).
- *(Optional)* a **Telegram bot token** for notifications/approvals.
- Local tools: `git`, an SSH client.

---

## 2. Provision the database (Neon — recommended)

1. Create a project at <https://console.neon.tech>.
2. In the Neon SQL editor, enable pgvector:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. Copy the **pooled** connection string. It looks like:
   ```
   postgresql://USER:PASSWORD@ep-xxxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require
   ```
   Save it — this is `DATABASE_URL`.

> The app auto-creates all tables on startup (`rsi/db.init_db()` runs
> `server/rsi/schema.sql`, which is idempotent). No manual migration needed.

**Alternative — AWS RDS:** create a PostgreSQL 15+ instance, connect with `psql`
and run `CREATE EXTENSION IF NOT EXISTS vector;` (RDS supports pgvector on PG
15.2+). Put the host in `DATABASE_URL`. Ensure the EC2 security group can reach
the RDS port (5432).

---

## 3. Generate required secrets

On any machine with Python + the `cryptography` package (or do it on the EC2 box
later):

```bash
# Token encryption key — REQUIRED in production. Generate ONCE and keep it stable.
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# A webhook secret and CD secret — any strong random strings:
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Record:
- `TOKEN_ENCRYPTION_KEY` (Fernet key above)
- `GITHUB_WEBHOOK_SECRET` (random string)
- `CD_WEBHOOK_SECRET` (random string, optional)

> If `TOKEN_ENCRYPTION_KEY` is ever lost or changed, all stored GitHub tokens
> become undecryptable and users must re-login. Store it in a password manager
> or AWS Secrets Manager.

---

## 4. DNS

Create two DNS records at your registrar:

| Record | Type | Points to |
| --- | --- | --- |
| `api.example.com` | A | (EC2 public IP — set after §5.1) |
| `app.example.com` | CNAME | `cname.vercel-dns.com` (Vercel gives the exact value in §9) |

Do `api.` now (you'll fill the IP after launching EC2); do `app.` in §9.

---

## 5. Backend on AWS EC2

### 5.1 Launch the instance
1. EC2 → **Launch instance**.
   - **AMI:** Ubuntu Server 24.04 LTS.
   - **Type:** `t3.small` (2 GB RAM) minimum — `t3.medium` recommended (LangGraph
     + the npx MCP subprocess are memory-hungry).
   - **Key pair:** create/download one for SSH.
   - **Storage:** 20 GB gp3.
2. **Security group** — allow inbound:
   - TCP **22** (SSH) — ideally from your IP only.
   - TCP **80** (HTTP — needed for Let's Encrypt).
   - TCP **443** (HTTPS).
3. Launch, then note the **public IPv4 address** and put it in the
   `api.example.com` **A record** (§4). Wait for DNS to propagate
   (`nslookup api.example.com`).

### 5.2 Install Docker
SSH in (`ssh -i key.pem ubuntu@<EC2_IP>`), then:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker   # apply group without re-login
```

### 5.3 Get the code
```bash
git clone <YOUR_REPO_URL> easyops
cd easyops
git checkout deploy        # or main, whichever branch you deploy
```

### 5.4 Create `server/.env`
```bash
cp server/.env.example server/.env
nano server/.env
```
Set these values (this is the production config):

```dotenv
APP_ENV=production
LOG_LEVEL=info
COOKIE_SAMESITE=lax          # 'lax' for same-domain (app./api.); 'none' if frontend is *.vercel.app

OPENAI_API_KEY=sk-...

GITHUB_CLIENT_ID=...          # from §6
GITHUB_CLIENT_SECRET=...      # from §6
GITHUB_WEBHOOK_SECRET=...     # the random string from §3

DATABASE_URL=postgresql://USER:PASSWORD@HOST/neondb?sslmode=require   # from §2

TOKEN_ENCRYPTION_KEY=...      # the Fernet key from §3

# Public URLs (no trailing slash)
PUBLIC_BASE_URL=https://api.example.com
FRONTEND_BASE_URL=https://app.example.com
CORS_ORIGINS=https://app.example.com
WEBHOOK_BASE_URL=https://api.example.com

# Optional — Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
TELEGRAM_WEBHOOK_URL=https://api.example.com/api/webhooks/telegram
TELEGRAM_ALLOWED_USER_IDS=123456789

# Optional — CD monitoring
CD_WEBHOOK_SECRET=...
```

> The `server/.env` is gitignored and stays only on the EC2 box. For stronger
> security, store these in **AWS Secrets Manager** / **SSM Parameter Store** and
> inject them at boot instead of a plaintext file.

### 5.5 Point Caddy at your domain
Edit `deploy/Caddyfile` and replace `api.example.com` with your real backend
subdomain:
```bash
nano deploy/Caddyfile
```

### 5.6 Build & run
```bash
docker compose -f deploy/docker-compose.prod.yml up -d --build
docker compose -f deploy/docker-compose.prod.yml logs -f server   # watch startup
```
On first boot Caddy will fetch a Let's Encrypt certificate (needs ports 80/443
open and DNS pointing at this box). The backend runs `init_db()` and creates all
tables automatically.

### 5.7 Verify the backend
```bash
curl -fsS https://api.example.com/health      # → {"status":"ok"} (or similar)
```
If the cert isn't ready, wait ~30s and retry; check `docker compose ... logs caddy`.

---

## 6. Create the GitHub OAuth App

1. GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Fill in:
   - **Homepage URL:** `https://app.example.com`
   - **Authorization callback URL:** `https://api.example.com/api/auth/callback`
     *(must exactly match `PUBLIC_BASE_URL` + `/api/auth/callback`)*
3. Create it; copy the **Client ID** and generate a **Client Secret**.
4. Put both into `server/.env` (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`) and
   restart the backend:
   ```bash
   docker compose -f deploy/docker-compose.prod.yml up -d
   ```

---

## 7. Frontend on Vercel

1. Go to <https://vercel.com> → **Add New… → Project** → import your Git repo.
2. **Configure project:**
   - **Root Directory:** `client`
   - **Framework Preset:** Vite (auto-detected).
   - **Build Command:** `npm run build` (default).
   - **Output Directory:** `dist` (default).
3. **Environment Variables** — add:
   | Name | Value |
   | --- | --- |
   | `VITE_API_BASE` | `https://api.example.com` |
4. Click **Deploy**. Vercel installs deps, runs `tsc -b && vite build`, and serves
   `dist/`.

> `VITE_API_BASE` is read at **build time** (`client/src/api/api.ts`). If you
> change it later you must **redeploy** for it to take effect.

### Add the custom domain
1. Vercel project → **Settings → Domains** → add `app.example.com`.
2. Vercel shows the exact DNS record (usually a CNAME to `cname.vercel-dns.com`).
   Create it at your registrar (this is the `app.` record from §4).
3. Wait for Vercel to verify and issue TLS.

---

## 8. Cross-site cookies — important

The browser must send the session cookie when the Vercel frontend calls the AWS
backend. Two supported setups:

**A) Same root domain (recommended).** `app.example.com` + `api.example.com`
share `example.com`, so they're the **same site**. Keep `COOKIE_SAMESITE=lax`.
Nothing else to do.

**B) Different sites** (e.g. frontend on `your-app.vercel.app`, backend on AWS):
they're **cross-site**, so the cookie needs `SameSite=None; Secure`:
- In `server/.env` set `COOKIE_SAMESITE=none` and restart the backend.
- `CORS_ORIGINS` must list the exact frontend origin (e.g.
  `https://your-app.vercel.app`).
- Both sides must be HTTPS (they are: Vercel + Caddy).

In **both** cases, `CORS_ORIGINS` must contain the frontend origin exactly (scheme
+ host, no trailing slash, no path).

---

## 9. (Optional) GitHub webhooks for a repo

You can register webhooks two ways:

- **From the dashboard:** after logging in, open a repo in the UI and
  **Initialize** it — the app calls the GitHub API to create the webhook pointing
  at `WEBHOOK_BASE_URL/api/webhooks/github`.
- **Manually:** repo → Settings → Webhooks → Add webhook:
  - Payload URL: `https://api.example.com/api/webhooks/github`
  - Content type: `application/json`
  - Secret: your `GITHUB_WEBHOOK_SECRET`
  - Events: Pushes, Pull requests, Workflow runs.

The webhook base URL is also editable at runtime from the dashboard (persisted in
the DB — no redeploy needed).

---

## 10. (Optional) Telegram & CD webhooks

- **Telegram:** set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_WEBHOOK_SECRET`, then set the
  bot webhook to `https://api.example.com/api/webhooks/telegram`. Users run
  `/link <github-username>` to the bot to receive their alerts.
- **CD failures:** point your pipeline at
  `https://api.example.com/api/webhooks/cd-failure` with header
  `X-CD-Webhook-Secret: <CD_WEBHOOK_SECRET>`.

---

## 11. End-to-end smoke test

1. `curl -fsS https://api.example.com/health` → ok.
2. Open `https://app.example.com` → click login → complete GitHub OAuth → you
   should land on the dashboard (`/home` → `/monitor`).
   - If login bounces back to the landing page, it's almost always cookies
     (§8) or `CORS_ORIGINS` not matching the frontend origin.
3. Initialize a repo from the UI; watch `docker compose ... logs -f server` build
   the RSI.
4. Open `/monitor` — the **SSE event stream** should connect (events appear live;
   no CORS errors in the browser console).
5. Open or push a PR on the monitored repo and watch a review event appear.

---

## 12. Updating / redeploying

**Backend (EC2):**
```bash
cd easyops
git pull
docker compose -f deploy/docker-compose.prod.yml up -d --build
```

**Frontend (Vercel):** push to the connected branch — Vercel auto-builds and
deploys. Changing `VITE_API_BASE` requires a redeploy.

---

## 13. Alternative — ECS Fargate (instead of EC2)

If you prefer managed containers:
- Build & push the backend image (`server/Dockerfile`) to **ECR**.
- ECS service with **`desiredCount: 1`** and **no autoscaling** (state is
  in-process — multiple tasks break SSE and the Telegram fix flow).
- Front it with an **Application Load Balancer** (enable sticky sessions; raise
  the idle timeout to ~3600s so SSE connections aren't cut).
- Use **ACM** for TLS on the ALB; point `api.example.com` at the ALB.
- Inject `server/.env` values as ECS task **secrets** from Secrets Manager.

Everything else (Vercel frontend, Neon DB, OAuth, cookies) is identical.

---

## 14. Production hardening checklist

- [ ] All secrets set; `TOKEN_ENCRYPTION_KEY` stored safely and stable.
- [ ] `APP_ENV=production`; cookies `Secure`; `COOKIE_SAMESITE` correct for your
      domain setup (§8).
- [ ] `CORS_ORIGINS` = your exact frontend origin only (no wildcards).
- [ ] Security group: SSH limited to your IP; only 80/443 public.
- [ ] DB backups: Neon PITR, or `pg_dump` cron / RDS automated backups.
- [ ] **Single backend instance only** (in-memory state — known constraint).
      Externalizing to Redis/Postgres is required before scaling out.
- [ ] Set up log shipping (CloudWatch agent) and an uptime check on `/health`.
- [ ] Rotate any credentials previously used in local development.

---

## 15. Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Login redirects back to landing page | Cookie not sent → check `COOKIE_SAMESITE` (§8) and that `CORS_ORIGINS` exactly matches the frontend origin. |
| Browser console shows CORS error | `CORS_ORIGINS` missing/typo; must include scheme + host, no trailing slash. |
| `redirect_uri` mismatch on GitHub | `PUBLIC_BASE_URL` doesn't match the OAuth App callback URL (§6). |
| Caddy can't get a cert | DNS A record not pointing to the EC2 IP yet, or ports 80/443 blocked in the security group. |
| Backend exits on startup with TOKEN_ENCRYPTION_KEY error | `APP_ENV=production` requires `TOKEN_ENCRYPTION_KEY` to be set (§3). |
| `init_db` fails on `CREATE EXTENSION vector` | pgvector not enabled — run `CREATE EXTENSION IF NOT EXISTS vector;` on the DB (§2). |
| SSE stream keeps dropping | If using an ALB, raise the idle timeout; with Caddy it streams by default. |
| GitHub MCP tools fail | The server image bundles Node for `npx @modelcontextprotocol/server-github`; check the container has outbound internet to npm + api.github.com. |
