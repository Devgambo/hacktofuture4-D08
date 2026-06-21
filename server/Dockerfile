# Backend: FastAPI + LangGraph DevOps agent.
# Build context is the repo root (see docker-compose.yml), so paths are server/*.
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Node.js is REQUIRED at runtime: the GitHub MCP client shells out to
# `npx -y @modelcontextprotocol/server-github` via stdio (server/agent/tools.py).
# git/curl are used by tooling and health checks.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl git ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# uv for fast, locked installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app/server

# Install dependencies first (cached layer) from the lockfile
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev

# Then the application code
COPY server/ ./

ENV PATH="/app/server/.venv/bin:$PATH"
EXPOSE 8000

# NOTE: single worker only. Shared state (jobs, event_log, SSE queues, dedup set)
# is in-process — running >1 worker/replica breaks SSE delivery and the Telegram
# "Request Fix" flow. Externalize to Redis/Postgres before scaling out.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
