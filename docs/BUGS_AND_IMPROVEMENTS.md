# Bugs & Improvements — EasyOps CI/CD Agent

Findings from a full read of the codebase. Each item lists **location →
problem → suggested fix**. Severity is best-effort; verify before acting.

> **Accuracy note:** an earlier automated pass claimed `server/rsi/schema.sql`
> was missing the `agent_memory`, `cd_provider_config`, and `cd_failure_history`
> tables. **This is false** — `grep "CREATE TABLE" server/rsi/schema.sql` shows
> all 12 tables are defined. That claim has been removed.
>
> The local `server/.env` contains real credentials, but it is **gitignored**
> (`.gitignore:9`) and **not committed** — so it is not a repo leak. It is still
> good practice to rotate any secrets that were shared and never commit `.env`.

---

## Critical (block production deployment)

### C1 — Hardcoded API base URL in the frontend (2 places)
- **Where:** `client/src/api/api.ts:6` and `client/src/pages/LandingPage/LandingPage.tsx:7` — both `const API_BASE = 'http://localhost:8000';`
- **Problem:** breaks in any non-local environment; duplicated so they can drift.
- **Fix:** `const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';` in `api.ts` only, and import it in `LandingPage`. Add `client/.env.example` with `VITE_API_BASE`.

### C2 — Hardcoded CORS origins
- **Where:** `server/main.py:97` — `allow_origins=["http://localhost:5173", "http://localhost:5174"]`
- **Problem:** production frontend origin is rejected.
- **Fix:** add `cors_origins: str` to `config.py`, read from env (comma-split), pass into `CORSMiddleware`.

### C3 — `TOKEN_ENCRYPTION_KEY` silent dev-fallback
- **Where:** `server/state_store.py` (key derivation block) — when unset, derives a key from `database_url` + GitHub secrets and only logs a warning.
- **Problem:** rotating any of those secrets silently changes the key and **orphans every stored token** (decryption fails). Easy to ship to prod unset.
- **Fix:** require an explicit key when `APP_ENV=production` (raise on startup if missing); keep the derived key for dev only.

### C4 — In-memory state blocks scaling & loses data on restart
- **Where:** `server/main.py` — `jobs` dict, event log, `_sse_queues`, `_reviewed_shas` dedup set; `server/agent/tools.py` — `_mcp_clients` cache.
- **Problem:** cannot run more than one instance; webhook-retry dedup and job history vanish on restart; MCP client cache grows unbounded (never invalidated on logout).
- **Fix:** persist jobs/events/dedup in Postgres (or Redis); add a `webhook_dedup` table keyed by GitHub delivery id; invalidate the MCP client on logout.

---

## High

### H1 — Bare `except:` clauses swallow everything
- **Where:** `server/main.py:1260`, `server/main.py:1325`.
- **Problem:** catches `KeyboardInterrupt`/`SystemExit` too; hides parse failures so partial/corrupt CD config/history is served silently.
- **Fix:** `except (json.JSONDecodeError, ValueError, TypeError) as e:` and log it.

### H2 — Blocking file I/O in an async handler
- **Where:** `server/main.py` `set_webhook_url` (~line 986) reads/writes the `.env` file with sync `open()`.
- **Problem:** blocks the event loop; also persisting settings by rewriting `.env` is fragile.
- **Fix:** store the webhook URL in the DB (preferred), or use `aiofiles` if file persistence is required.

### H3 — No validation before `repo.split("/")`
- **Where:** `server/main.py:268`, `server/webhook_manager.py:71`, and similar unpacking sites.
- **Problem:** input like `justname` or `a/b/c` raises `IndexError`/`ValueError` (500s).
- **Fix:** validate `"/" in repo` and use `owner, name = repo.split("/", 1)`; return `400` otherwise.

### H4 — Public webhook endpoints lack rate limiting & body-size caps
- **Where:** `/api/webhooks/github`, `/api/webhooks/cd-failure`, `/api/webhooks/telegram` in `main.py`.
- **Problem:** unbounded payloads / request floods → memory exhaustion / DoS. CD `error_logs` can be arbitrarily large.
- **Fix:** add rate limiting (e.g. SlowAPI), enforce a max body size, and truncate `error_logs` on ingest (e.g. `[:100_000]`).

### H5 — Database initialized lazily
- **Where:** DB connects on first use (`rsi/db.py`, called from request paths).
- **Problem:** a bad `DATABASE_URL` lets the app "start" healthy then fail on first request; health checks can't catch it.
- **Fix:** eager `await init_db()` inside the FastAPI `lifespan`; fail startup loudly on error.

### H6 — Frontend type safety: `repos: any[]`
- **Where:** `client/src/context/AuthContext.tsx` and `client/src/api/api.ts` use `any[]`, but a `UserRepo` type already exists in `api.ts`.
- **Problem:** loses compile-time safety on repo handling.
- **Fix:** type as `UserRepo[]` everywhere. Also fix the `@types/react-router-dom` v5 dep against runtime v7 (update or remove — RR7 ships its own types).

### H7 — Missing error/loading states in the UI
- **Where:** `client/src/pages/OAuthScreen/OAuthScreen.tsx:7` (`const error = null;` — error UI can never render); `client/src/pages/MonitorScreen/MonitorScreen.tsx:~57` (`.catch(console.error)` only).
- **Problem:** users get no feedback on failures.
- **Fix:** real error state + retry; surface via Sonner toasts. Add a loading skeleton to `Topbar` while auth resolves.

---

## Medium

### M1 — Inconsistent API error parsing
- **Where:** `client/src/api/api.ts` — some calls parse `{ detail }` from the body (e.g. `updateWebhookUrl`), most just throw `res.status`.
- **Fix:** one shared `async function handleFetchError(res)` that tries `{ detail }`, falls back to `statusText`; use it in every call.

### M2 — `logout` uses `window.location.href`
- **Where:** `client/src/context/AuthContext.tsx` logout.
- **Fix:** use router `navigate('/', { replace: true })`; toast on logout API failure instead of silent `console.error`.

### M3 — SSE robustness
- **Where:** `connectEventStream` (`api.ts`) / `MonitorScreen` effect.
- **Problem:** no reconnect/backoff; React StrictMode double-mounts the effect → duplicate fetch.
- **Fix:** exponential-backoff reconnect; guard the effect with an `AbortController`.

### M4 — Accessibility gaps
- **Where:** `role="button"` `<div>`s in `AboutUsPage`/`ArchitecturePage` lack `onKeyDown`; search input in `InitRepoScreen` lacks `aria-label`.
- **Fix:** add Enter/Space key handlers and `aria-label`s; manage focus in modals.

### M5 — Backend observability
- **Where:** throughout `server/`.
- **Problem:** plain string logs, no correlation/job ids, sparse type hints.
- **Fix:** structured logging (e.g. `structlog`) with a per-request/job id; add return-type hints (`state_store._json_value`, `auth.py`, `telegram_notifier._fix_request_callback` typed `object`).

### M6 — Hardcoded LLM model ids
- **Where:** `server/config.py:16,18,20`.
- **Fix:** read from env (`CODING_MODEL_ID`, etc.) with current values as defaults; document in `.env.example`.

### M7 — Trivial uncommitted diff
- **Where:** `client/src/api/api.ts` — only a comment was removed (`// send session cookie`).
- **Fix:** commit or discard so the tree is clean before deployment work.

---

## Modularity (explicitly requested)

### Backend
- **Split `server/main.py` (~1300 lines).** It mixes routing, webhook HMAC/parse,
  agent dispatch, settings persistence, and SSE.
  - Introduce a `server/routers/` package: `auth.py`, `webhooks.py`, `repos.py`,
    `jobs.py`, `settings.py`, `events.py`, each an `APIRouter` included in `main.py`.
  - Extract webhook signature verification + payload parsing into
    `server/webhooks/` helpers.
  - Add an `AgentDispatcher` service (`handle_ci_failure`, `handle_pr_review`,
    `handle_cd_failure`) so `main.py` no longer reaches directly into
    `agent/graph.py` etc. — this decouples transport from agent logic and makes
    both unit-testable.
- **Centralize cross-cutting config:** env-drive CORS, model ids, and the webhook
  URL (move it out of `.env` rewriting into the DB).
- **MCP client lifecycle:** add `invalidate_mcp_client(token)` in `agent/tools.py`
  and call it from logout to bound the cache.

### Frontend
- **Extract data hooks** to remove repeated fetch/SSE wiring from pages:
  `useMonitoredRepos()`, `useEventStream()`, `useJobs()`.
- **Split large components:** `MonitorScreen.tsx` (~293 lines) → `EventLog`,
  `RepoList`, `JobList`; `DestructurePage.tsx` (~288 lines) → per-tab components.
- **Single source of truth for API base + error handling** (see C1, M1).
- Consider `React.lazy` route-level code splitting once pages grow.

### Project-wide
- **Add a test suite.** Today only `test_parser.py` exists.
  - Backend `server/tests/` (pytest + a Postgres test fixture): OAuth/session
    expiry, webhook HMAC + dispatch, repo-name validation, memory similarity.
  - Frontend Vitest + React Testing Library: AuthContext init, protected routes,
    API error handling, event filtering.
- **CI:** add `.github/workflows/` to run lint + type-check + tests on PRs (none exist).

---

## Quick-win checklist
- [ ] C1 `VITE_API_BASE`, de-dupe LandingPage
- [ ] C2 env-driven CORS
- [ ] C3 require `TOKEN_ENCRYPTION_KEY` in prod
- [ ] H1 replace bare `except:`
- [ ] H3 validate repo names
- [ ] H5 eager DB init in lifespan
- [ ] H6 `UserRepo[]` typing + fix RR types dep
- [ ] H7 / M1 / M2 real error states + shared error util + router logout
- [ ] M7 clean the working tree
