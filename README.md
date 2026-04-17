# DevOps Agent - Team BROKENCODE

DevOps Agent is an autonomous CI/CD pipeline monitor, PR reviewer, and issue fixer powered by LangChain and LangGraph. Built for modern DevOps workflows, it seamlessly integrates with GitHub to automatically analyze CI failures, review Pull Requests based on a custom scoring system, and monitor CD pipelines across multiple cloud providers (AWS, GCP, Azure).

## Features

- **Autonomous CI Fixer**: Automatically detects CI workflow failures via GitHub webhooks, triggers an AI agent (GPT-4o) to trace the root cause using the Repository Structure Index (RSI), and generates a fix Pull Request autonomously.
- **Intelligent PR Reviews**: Three-tier quality gate for Pull Requests:
  - **Score ≥ 75**: Auto-merges successful, clean code.
  - **Score 50–74**: Triggers manual Telegram approval before merging.
  - **Score < 50**: Blocks CI/CD and triggers an automated fix agent to suggest improvements based on review findings.
- **CD Pipeline Monitoring**: Monitors deployment pipelines across AWS, GCP, Azure, and custom providers. It aggregates metrics (Deployment Health, Error Rate, Latency) and automates rollbacks and anomaly detection.
- **RSI (Repository Structure Index)**: An intelligent codebase ingestion pipeline that maps the structure of a repository, enabling the AI to precisely fetch code context dynamically using RAG.
- **Telegram Moderation**: Deep integration with Telegram for real-time pipeline notifications, PR review summaries, and fast manual approvals via interactive buttons.
- **Multi-Tenant OAuth**: Secure, per-user GitHub OAuth token integration for handling GitHub MCP operations and repository webhooks in isolation.

## Architecture
<img width="6548" height="2766" alt="fossflow-export-2026-04-16T17_33_18 977Z" src="https://github.com/user-attachments/assets/88bad79f-94b5-40d3-89a1-820b7f0eb261" />


## Technology Stack

**Backend:**
- Python 3.13+, FastAPI, Uvicorn
- LangChain, LangGraph, Model Context Protocol (MCP)
- PostgreSQL (asyncpg) for RSI storage and event history
- SSE (Server-Sent Events) for real-time frontend logs

**Frontend:**
- React 19, TypeScript, Vite
- Tailwind CSS 4
- React Router

## Setup & Installation

### Prerequisites
- Python 3.13+
- Node.js 20+
- PostgreSQL instance running
- GitHub App with Webhook access configured
- Telegram Bot Token

### Backend Setup

1. **Navigate to the server directory**:
   ```bash
   cd server
   ```
2. **Install dependencies** (assuming a virtual environment):
   ```bash
   uv sync
   ```
3. **Configuration**:
   Ensure you have configured environment variables (GitHub tokens, OpenAI/LLM keys, Database URL, Telegram tokens).
4. **Run the API server**:
   ```bash
   uvicorn main:app --reload --port 8000
   ```

### Frontend Setup

1. **Navigate to the client directory**:
   ```bash
   cd client
   ```
2. **Install dependencies**:
   ```bash
   npm install
   ```
3. **Run the dev server**:
   ```bash
   npm run dev
   ```

## Architecture Overview

Our autonomous LangGraph agent maps GitHub/CD webhook events to targeted workflows:
1. **CI Webhooks**: On failure, the system reads repo RSI, diagnoses the trace, and opens a new PR with a fix.

2. **PR Webhooks**: Upon PR creation/update, the review agent calculates a comprehensive score and coordinates GitHub Commit Statuses and Telegram gates.
3. **CD Failure Hooks**: Detects deployment anomalies, pulling provider specific logs and prompting an LLM diagnosis, taking predefined rollback steps if severe.

## Preventing Vendor Lock-in (CD Monitoring)

A major feature of this project is its robust abstraction layer for Continuous Deployment (CD) failures, completely decoupling the platform from any single cloud provider's proprietary webhook or logging ecosystem.

- **Unified Interface:** We use an adapter pattern (`cd_providers.get_cd_adapter()`) that dynamically parses failures based on the exact deployment target.
- **Normalized Context:** Whether the failure comes from AWS (CloudWatch/CodeDeploy), GCP (Cloud Logging), Azure (Monitor), or a custom internal webhook, it undergoes normalization into a standardized `CDFailureContext`. 
- **LLM Agnostic Diagnosis:** Because the AI agent only interfaces with the abstracted `CDFailureContext` to diagnose errors and recommend rollbacks, teams can migrate across cloud providers without changing their root-cause analysis pipelines.

## RSI (Repository Structure Index) Schema

To feed the LangGraph agent with precise codebase context without blowing up the LLM token limit, our RSI system maps the entire codebase into a vector-backed PostgreSQL schema:

- `rsi_file_map`: Stores file paths, role tags (`source`, `config`), line counts, and short AI-generated descriptions for every codebase file.
- `rsi_symbol_map`: Tracks the exact line boundaries of defined classes and functions to allow targeted, high-precision code retrieval.
- `rsi_imports`: Acts as a dependency graph index. Traces module connections backward and forward to assess the blast radius of proposed code changes.
- `rsi_repo_summary`: A high-level cache holding the tech stack footprint, global entry points, and project description, functioning as a lightweight `CLAUDE.md`.
- `agent_memory`: Uses a **1024-dimensional pgvector HNSW index** mapped via Cosine similarity to store episodic memory. Past successful fixes ("error signature" to "root cause" mapping) are dynamically injected as few-shot prompts using RAG during future CI jobs.

---
*Built with ❤️ for Hack To Future 4 by Team BROKENCODE*
