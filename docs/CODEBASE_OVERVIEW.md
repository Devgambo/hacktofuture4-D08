# Codebase Overview — EasyOps CI/CD Agent

> Autonomous CI/CD pipeline monitor, PR reviewer, and issue fixer built on
> LangGraph + GitHub, with episodic memory and multi-cloud CD diagnosis.

This document explains **what every part of the codebase does**. For known bugs
and improvement ideas see [`BUGS_AND_IMPROVEMENTS.md`](./BUGS_AND_IMPROVEMENTS.md);
for how to ship it see [`DEPLOYMENT.md`](./DEPLOYMENT.md).

---

## 1. What it does

EasyOps connects to a GitHub repository (via OAuth + webhooks) and runs three
autonomous agent workflows:

| Workflow | Trigger | What it does |
| --- | --- | --- |
| **CI failure fix** | GitHub `check_run` / workflow failure | Parses error logs, pulls repository context (RSI), searches **episodic memory** for similar past fixes, generates a fix and opens a PR. On merge it stores the fix back into memory. |
| **PR review** | GitHub `pull_request` | Reviews the diff with repo context, produces a **confidence score (0–100)**. ≥75 → auto-merge; 50–74 → gate and request human approval (via Telegram); <50 → block and hand off to the fix agent. |
| **CD failure diagnosis** | CD webhook (`/api/webhooks/cd-failure`) | Normalizes logs from AWS / Azure / GCP / custom via provider adapters, runs an LLM diagnosis, and reports root cause (e.g. to Telegram). |

Real-time progress is streamed to the dashboard over **Server-Sent Events (SSE)**.

---

## 2. Tech stack

**Backend (`server/`)**
- Python **3.13** (`server/.python-version`), managed by **uv** (`uv.lock`)
- **FastAPI** + **Uvicorn** (`server/main.py`)
- **LangChain / LangGraph / MCP** (`langchain-mcp-adapters`) for agent orchestration and GitHub tooling
- **PostgreSQL** via **asyncpg**, with **pgvector** for embeddings
- **OpenRouter** as the LLM gateway (`OPENROUTER_BASE_URL`), models `gpt-4o` / `gpt-4o-mini`
- **sse-starlette** for event streaming; **cryptography** for token encryption
- Cloud SDKs: `boto3` (AWS), `azure-identity` + `azure-monitor-query`, `google-cloud-logging` + `google-cloud-monitoring`
- `python-telegram-bot` for notifications/approvals

**Frontend (`client/`)**
- **React 19**, **TypeScript ~6**, **Vite 8**, **Tailwind CSS 4**, **React Router 7**
- **Sonner** for toasts

---

## 3. Directory tree (annotated)

```
hacktofuture4-D08/
├── README.md                      # Project marketing/overview + diagrams
├── test_parser.py                 # Only test: RSI parser (Python/JS) unit test
├── pyrightconfig.json             # Pyright type-check config
├── docs/                          # (this folder) generated documentation
├── server/                        # Python backend
│   ├── main.py                    # FastAPI app: routes, webhooks, SSE, dispatch (~1300 lines)
│   ├── config.py                  # pydantic-settings: env vars, model ids
│   ├── auth.py                    # GitHub OAuth login/callback/logout
│   ├── messages.py               # Event/message formatting helpers
│   ├── state_store.py             # Encrypted session + per-repo token storage
│   ├── telegram_notifier.py       # Telegram bot send/receive + approvals
│   ├── webhook_manager.py         # Register/track GitHub webhooks per repo
│   ├── pyproject.toml / uv.lock   # Dependencies (uv)
│   ├── .env.example               # Env var template (real .env is gitignored)
│   ├── agent/
│   │   ├── graph.py               # Main CI-failure fix LangGraph
│   │   ├── review_graph.py        # PR review LangGraph (scoring/gating)
│   │   ├── cd_monitor_graph.py    # CD failure diagnosis LangGraph
│   │   ├── tools.py               # LangGraph/MCP tools (GitHub etc.); MCP client cache
│   │   └── prompts.py             # LLM prompt templates
│   ├── cd_providers/
│   │   ├── base.py                # Adapter interface (normalize logs/status)
│   │   ├── aws_adapter.py         # CloudWatch / CodeDeploy
│   │   ├── azure_adapter.py       # Azure Monitor
│   │   ├── gcp_adapter.py         # Cloud Logging / Monitoring
│   │   └── custom_adapter.py      # Generic/custom CD payloads
│   ├── memory/
│   │   ├── embedder.py            # Text → embedding vectors
│   │   └── store.py               # Episodic memory CRUD + vector similarity search
│   └── rsi/                       # Repository Structure Index
│       ├── parser.py              # Parse files → symbols/imports/line counts
│       ├── builder.py             # Build the RSI for a repo
│       ├── db.py                  # asyncpg pool, init_db(), RSI queries
│       └── schema.sql             # Full Postgres schema (12 tables, idempotent)
└── client/                        # React frontend
    ├── index.html                 # Vite entry HTML
    ├── vite.config.ts             # Vite + react + tailwind plugins
    ├── package.json               # Scripts & deps
    ├── tsconfig*.json             # TS configs
    ├── eslint.config.js           # Lint config
    └── src/
        ├── main.tsx               # React root render
        ├── App.tsx                # Router + AuthProvider + protected routes
        ├── api/api.ts             # Typed HTTP client + SSE connector (API_BASE)
        ├── context/AuthContext.tsx# Auth state (user, repos, login/logout)
        ├── components/            # DashboardLayout, Sidebar, Topbar, LoadingScreen, TelegramModal
        ├── pages/                 # LandingPage, OAuthScreen, InitRepoScreen, MonitorScreen, AboutUsPage, ArchitecturePage, DestructurePage
        ├── styles/globals.css     # Material 3 tokens + Tailwind utilities
        └── types/index.ts         # Shared TS types
```

---

## 4. Backend — file reference

### Core (`server/`)
| File | Responsibility |
| --- | --- |
| `main.py` | FastAPI app & `lifespan` (initializes DB, Telegram, MCP). Hosts all routes, parses GitHub/CD/Telegram webhooks, dispatches to the agent graphs, maintains in-memory job/event/SSE state, exposes the SSE stream. **Largest, most coupled file.** |
| `config.py` | `pydantic-settings` `Settings` object. Holds env vars and hardcoded model ids (`coding_model_id="gpt-4o"`, `reasoning_model_id`/`fast_model_id="gpt-4o-mini"`, lines 16/18/20). |
| `auth.py` | GitHub OAuth: redirect to GitHub, handle callback, create encrypted session, logout. |
| `state_store.py` | Stores/retrieves GitHub tokens encrypted with `TOKEN_ENCRYPTION_KEY` (dev fallback derives a key from other secrets), session lookup + expiry, per-repo token resolution. |
| `messages.py` | Formats human-readable event/notification messages. |
| `telegram_notifier.py` | Sends notifications and handles inbound Telegram updates (approve/reject gated PRs); user allow-list. |
| `webhook_manager.py` | Creates and tracks GitHub webhooks for a repo (splits `owner/name`). |

### Agent (`server/agent/`)
| File | Responsibility |
| --- | --- |
| `graph.py` | LangGraph state machine for **CI failure → fix PR**: gather logs/context, query memory, generate patch, open PR. |
| `review_graph.py` | LangGraph for **PR review**: diff + RSI analysis → confidence score → auto-merge / gate / block. |
| `cd_monitor_graph.py` | LangGraph for **CD diagnosis**: adapter-normalized logs → LLM root-cause. |
| `tools.py` | Tool definitions (GitHub via MCP, etc.). Caches `MultiServerMCPClient` per token in `_mcp_clients`. |
| `prompts.py` | Prompt templates for the three graphs. |

### CD providers (`server/cd_providers/`)
Adapter pattern: `base.py` defines the interface; `aws_adapter.py`,
`azure_adapter.py`, `gcp_adapter.py`, `custom_adapter.py` each normalize their
provider's logs/status into a common shape consumed by `cd_monitor_graph.py`.

### Memory (`server/memory/`)
| File | Responsibility |
| --- | --- |
| `embedder.py` | Produces embedding vectors for error signatures / fixes. |
| `store.py` | Reads/writes `agent_memory`, performs vector similarity search to find prior fixes for similar failures. |

### RSI — Repository Structure Index (`server/rsi/`)
| File | Responsibility |
| --- | --- |
| `parser.py` | Parses a source file into symbols (functions/classes), imports, and line counts (Python & JS). |
| `builder.py` | Walks a repo and builds its RSI from parsed files. |
| `db.py` | asyncpg connection pool (`min_size=2, max_size=10`), `init_db()` runs `schema.sql`, RSI query helpers. |
| `schema.sql` | **Complete** idempotent schema (all `CREATE TABLE IF NOT EXISTS`), incl. inline column/embedding migrations. |

#### Database tables (from `schema.sql`)
| Table | Purpose |
| --- | --- |
| `rsi_file_map` | Indexed files + metadata (role tag, line count, description). |
| `rsi_symbol_map` | Functions/classes with line ranges. |
| `rsi_imports` | Per-file import/dependency edges. |
| `rsi_sensitivity` | Flags sensitive files (secrets/config). |
| `rsi_repo_summary` | Repo-level summary (stack, entry points). |
| `user_sessions` | Encrypted GitHub tokens, expiry, Telegram chat id. |
| `repo_credentials` | Per-repo token storage (FK to sessions, `ON DELETE CASCADE`). |
| `repo_webhooks` | Registered webhook tracking. |
| `agent_fix_jobs` | Maps error logs → resulting PR (feeds memory). |
| `agent_memory` | pgvector-indexed episodic memory of past fixes. |
| `cd_provider_config` | Per-repo CD provider settings. |
| `cd_failure_history` | CD failures + LLM diagnosis. |

---

## 5. Backend — API reference

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/auth/github` (login) | GET | Start GitHub OAuth. |
| `/api/auth/callback` | GET | OAuth callback; sets session cookie. |
| `/api/auth/me` | GET | Current user + their repos. |
| `/api/auth/logout` | POST | Clear session. |
| `/api/webhooks/github` | POST | GitHub events (push, PR, check_run, installation). |
| `/api/webhooks/cd-failure` | POST | CD failure ingestion. |
| `/api/webhooks/telegram` | POST | Telegram updates (approvals). |
| `/api/repos/{owner}/{repo}/initialize` | POST | Build RSI + start monitoring. |
| `/api/repos/monitored` | GET | List monitored repos. |
| `/api/repos/{owner}/{repo}/monitoring` | DELETE | Stop monitoring. |
| `/api/github/repos` | GET | User's GitHub repos (optional `?q=`). |
| `/api/jobs` / `/api/jobs/{id}` | GET | Job list / detail. |
| `/api/events` | GET (SSE) | Real-time event stream. |
| `/api/settings/webhook-url` | GET/POST | Read/update public webhook URL. |
| `/api/memory/stats` | GET | Episodic memory stats. |
| `/health` | GET | Health check. |

---

## 6. Frontend — file reference

| Area | Responsibility |
| --- | --- |
| `main.tsx` | Mounts `<App/>`. |
| `App.tsx` | Sets up router, `AuthProvider`, protected vs public routes, post-auth redirect handling. |
| `api/api.ts` | Typed fetch wrapper to the backend (`API_BASE`, `credentials:'include'`), all endpoint calls, and `connectEventStream` SSE helper. Defines response types incl. `UserRepo`. |
| `context/AuthContext.tsx` | Holds `user` + `repos`, `refetch` on mount, `logout`. Exposes `useAuth()`. |
| `components/DashboardLayout` | App shell; persists sidebar collapse to `localStorage`, drives `--sidebar-width`. |
| `components/Sidebar` / `Topbar` | Navigation + user chip. |
| `components/LoadingScreen` | Full-screen loader. |
| `components/TelegramModal` | Telegram connect UI. |
| `pages/LandingPage` | Marketing page; starts OAuth (also hardcodes `API_BASE`). |
| `pages/OAuthScreen` | Integration settings (currently `error` hardcoded to `null`). |
| `pages/InitRepoScreen` | Search GitHub repos, initialize monitoring. |
| `pages/MonitorScreen` | Live dashboard: jobs, SSE event log (capped at 100), repo management. |
| `pages/AboutUsPage` / `ArchitecturePage` / `DestructurePage` | Informational/marketing pages. |
| `styles/globals.css` | Material Design 3 tokens + Tailwind custom utilities. |
| `types/index.ts` | Shared TS types. |

### Routes
| Path | Protected | Page |
| --- | --- | --- |
| `/` | No | LandingPage |
| `/about`, `/about/architecture`, `/about/destructure` | No | About / Architecture / Destructure |
| `/oauth` | Yes | OAuthScreen |
| `/init` | Yes | InitRepoScreen |
| `/monitor` | Yes | MonitorScreen |

---

## 7. Key data flows

**Auth (OAuth):** Landing page stores a `postAuthRedirect` in `sessionStorage`,
sends the user to `…/api/auth/github` → GitHub → `…/api/auth/callback` (server
sets an HTTP session cookie, encrypts the token into `user_sessions`) → redirect
to `/` → `AuthContext` calls `/api/auth/me` → post-auth handler navigates to
`/init`.

**Webhook → agent:** GitHub posts to `/api/webhooks/github`; `main.py` verifies
the HMAC signature, parses the event, and dispatches to the matching graph
(`graph.py` / `review_graph.py`). CD systems post to `/api/webhooks/cd-failure`
→ adapter normalizes → `cd_monitor_graph.py`.

**Live updates (SSE):** the agents push progress events into an in-memory log and
per-client queues; the frontend `connectEventStream` subscribes to `/api/events`
and the MonitorScreen renders them (keeping the last 100).

---

## 8. Environment variables (`server/.env.example`)

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` | LLM gateway. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_WEBHOOK_SECRET` | OAuth + webhook verification. |
| `DATABASE_URL` | PostgreSQL (pgvector) connection. |
| `TOKEN_ENCRYPTION_KEY` | Encrypts stored GitHub tokens (**set explicitly in prod**). |
| `APP_ENV`, `LOG_LEVEL` | Runtime mode / logging. |
| `WEBHOOK_BASE_URL` | Public HTTPS base for GitHub callbacks. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_ALLOWED_USER_IDS` | Telegram integration. |
| `CD_WEBHOOK_SECRET` | CD webhook verification. |
| `AWS_*`, `AZURE_*`, `GCP_*` / `GOOGLE_APPLICATION_CREDENTIALS` | Optional cloud CD access. |

Frontend needs `VITE_API_BASE` (currently hardcoded — see bug report).

---

## 9. Testing

Only `test_parser.py` (root) exists — it tests RSI `parse_file()` for Python and
JS. Run with `python -m pytest test_parser.py -v`. No backend API tests, no
frontend tests yet.
