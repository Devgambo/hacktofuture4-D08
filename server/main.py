"""
DevOps Agent API — FastAPI application.
Handles GitHub webhooks, dispatches agent jobs, and streams events to the frontend.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from config import get_settings
from auth import router as auth_router, get_token_for_repo
from telegram_notifier import TelegramAuthError, TelegramNotifier
from webhook_manager import create_webhook
# B40: removed unused import of get_webhook_id

# B3: use the canonical message formatters from messages.py
from messages import (
    ci_failed_started,
    ci_completed,
    ci_failed,
    pr_main_update,
    pr_review_completed,
    pr_failed,
)
from state_store import get_telegram_chat_id_for_repo as _get_telegram_chat_id

# ── Logging ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("devops_agent")

# ── In-memory stores (swap for Redis/DB in production) ──
jobs: dict[str, dict] = {}
event_log: list[dict] = []

# B36: per-subscriber queues for push-based SSE (no polling)
_sse_queues: set[asyncio.Queue] = set()

# Dedup cache for PR reviews
_reviewed_shas: set[str] = set()

telegram_notifier: TelegramNotifier | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down shared async resources."""
    global telegram_notifier

    settings = get_settings()

    from rsi.db import init_db

    await init_db()

    telegram_notifier = TelegramNotifier(
        token=settings.telegram_bot_token,
        webhook_secret=settings.telegram_webhook_secret,
        webhook_url=settings.telegram_webhook_url,
        allowed_user_ids=settings.telegram_allowed_user_id_list,
    )
    telegram_notifier.register_fix_callback(_handle_fix_request)
    await telegram_notifier.start()

    try:
        yield
    finally:
        if telegram_notifier:
            await telegram_notifier.stop()

        from agent.tools import shutdown_mcp
        from rsi.db import close_db

        await shutdown_mcp()
        await close_db()

app = FastAPI(
    title="DevOps Agent API",
    description="Autonomous CI fixer and PR reviewer powered by GPT-4o",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the React dev server (with credentials for cookies)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount auth router
app.include_router(auth_router)

# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _verify_signature(payload_body: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _emit_event(event_type: str, data: dict) -> None:
    """Push an event to the in-memory log and notify all SSE subscribers."""
    entry = {
        "id": str(uuid.uuid4()),
        "type": event_type,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    event_log.append(entry)
    # Keep at most 500 events in memory
    if len(event_log) > 500:
        event_log.pop(0)
    # B36: push to every connected SSE subscriber immediately (no polling)
    for q in _sse_queues:
        try:
            q.put_nowait(entry)
        except asyncio.QueueFull:
            pass  # slow consumer — skip rather than block


async def _notify_telegram(message: str, *, repo: str | None = None) -> None:
    """Send a Telegram notification targeted at the owner of *repo*.

    If *repo* is provided, the notification is sent only to the Telegram
    chat_id stored in that user's session.  This prevents broadcasts when
    multiple users are working simultaneously.

    If no chat_id is found (the user hasn't run /link yet) the notification
    is silently skipped — no broadcast to unrelated users.
    """
    if not telegram_notifier:
        return

    chat_ids: list[int] = []
    if repo:
        chat_id = await _get_telegram_chat_id(repo)
        if chat_id:
            chat_ids = [chat_id]
        else:
            logger.debug(
                "No Telegram chat_id for repo=%s — notification skipped (user not linked)", repo
            )
            return

    await telegram_notifier.notify(message, chat_ids=chat_ids)


# ─────────────────────────────────────────────────────────
# Background task dispatchers
# ─────────────────────────────────────────────────────────

async def _handle_ci_failure(payload: dict, job_id: str) -> None:
    """Process a CI failure event through the LangGraph agent.
    If RSI data doesn't exist yet for this repo, runs cold-start first."""
    jobs[job_id]["status"] = "running"
    repo_name = payload.get("repository", {}).get("full_name", "")
    workflow_run = payload.get("workflow_run", {})
    _emit_event("job_started", {"job_id": job_id, "repo": repo_name})

    # B3: use messages.py formatters; extract fields from payload here
    await _notify_telegram(ci_failed_started(
        repo=repo_name,
        branch=workflow_run.get("head_branch", "unknown"),
        workflow=workflow_run.get("name", "unknown"),
        actor=workflow_run.get("triggering_actor", {}).get("login", "unknown"),
        job_id=job_id,
        run_url=workflow_run.get("html_url", ""),
    ), repo=repo_name)

    # Look up the user's OAuth token for this repo
    github_token = await get_token_for_repo(repo_name) or get_settings().github_token

    try:
        # Check if RSI data exists; if not, run cold-start first
        from rsi import db as rsi_db
        pool = await rsi_db.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM rsi_file_map WHERE repo_id=$1 LIMIT 1", repo_name
            )
        if not row:
            logger.info("No RSI data for %s — running cold-start before agent", repo_name)
            _emit_event("cold_start_started", {"repo": repo_name, "trigger": "ci_failure"})
            from rsi.builder import cold_start_build
            await cold_start_build(repo_name, github_token=github_token)
            _emit_event("cold_start_completed", {"repo": repo_name})

        from agent.graph import run_agent
        result = await run_agent(payload, job_id, _emit_event, github_token=github_token)
        
        if result.get("status") in ("pr_failed", "pr_skipped") or not result.get("final_pr_url"):
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["result"] = result
            jobs[job_id]["error"] = result.get("error", "PR was not created")
            _emit_event("job_failed", {"job_id": job_id, "error": result.get("error", "")})
            await _notify_telegram(ci_failed(repo_name, job_id, result.get("error", "PR creation failed")), repo=repo_name)
        else:
            jobs[job_id]["status"] = "pr_opened"
            jobs[job_id]["result"] = result
            pr_url = result.get("final_pr_url", "")
            _emit_event("job_completed", {"job_id": job_id, "pr_url": pr_url})
            
            pr_number_str = pr_url.rstrip("/").split("/")[-1] if pr_url else "0"
            try:
                pr_number = int(pr_number_str)
            except ValueError:
                pr_number = 0
                
            if pr_number and telegram_notifier:
                from messages import ci_completed_approval
                msg = ci_completed_approval(repo_name, job_id, pr_url)
                
                chat_ids: list[int] = []
                chat_id = await _get_telegram_chat_id(repo_name)
                if chat_id:
                    chat_ids = [chat_id]
                    await telegram_notifier.notify_pr_approval(msg, repo_name, pr_number, chat_ids=chat_ids)
                else:
                    logger.debug("No Telegram chat_id for repo=%s — PR approval notification skipped", repo_name)
            else:
                await _notify_telegram(ci_completed(repo_name, job_id, pr_url), repo=repo_name)
    except Exception as e:
        logger.exception("Agent failed for job %s", job_id)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        _emit_event("job_failed", {"job_id": job_id, "error": str(e)})
        await _notify_telegram(ci_failed(repo_name, job_id, str(e)), repo=repo_name)


async def _handle_push_to_main(payload: dict) -> None:
    """Trigger RSI delta updates when code is pushed to the default branch."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    github_token = await get_token_for_repo(repo) or get_settings().github_token
    _emit_event("rsi_update_started", {"repo": repo})
    try:
        from rsi.builder import delta_update
        commits = payload.get("commits", [])
        before  = payload.get("before", "")
        after   = payload.get("after", "")
        await delta_update(repo, commits, github_token=github_token, before=before, after=after)
        _emit_event("rsi_update_completed", {"repo": repo})
    except Exception as e:
        logger.exception("RSI delta update failed for %s", repo)
        _emit_event("rsi_update_failed", {"repo": repo, "error": str(e)})

async def _post_commit_status(repo: str, sha: str, state: str, token: str, description: str = "") -> None:
    """Post a commit status to GitHub."""
    import httpx
    owner, repo_name = repo.split("/")
    url = f"https://api.github.com/repos/{owner}/{repo_name}/statuses/{sha}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "state": state,
        "context": "devops-agent/pr-review",
        "description": description[:140] if description else "",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 201:
                logger.warning("Failed to post commit status %s for %s (%s): %s", state, repo, sha, resp.text)
    except Exception as e:
        logger.warning("Exception posting commit status: %s", e)

async def _handle_fix_request(job_id: str) -> str:
    """Called by Telegram notifier when user clicks 'Request Fix' after a low-score review.

    Retrieves the stored review state, runs run_pr_fix, and returns the fix PR URL.
    """
    job = jobs.get(job_id, {})
    repo = job.get("repo")
    pr_number = job.get("pr_number")
    
    if not repo or not pr_number:
        logger.warning("[fix_request] Missing repo or pr_number for job %s", job_id)
        return ""
    review_state = job.get("result", {})
    if not review_state:
        logger.warning("[fix_request] No review state found for job %s", job_id)
        return ""

    review_result   = review_state.get("review_result", {})
    rsi_context_str = review_state.get("rsi_context_str", "")
    pr_branch       = review_state.get("pr_branch", "")
    changed_files   = [f["path"] for f in review_state.get("changed_files", [])
                       if f.get("status") != "removed"]
    # Reconstruct diff from changed_files patches
    pr_diff = "\n\n".join(
        f"--- {f['path']}\n{f.get('patch', '')}"
        for f in review_state.get("changed_files", [])
        if f.get("patch")
    )

    if not pr_branch:
        logger.warning("[fix_request] No pr_branch in review state for job %s", job_id)
        return ""

    github_token = await get_token_for_repo(repo) or get_settings().github_token

    fix_job_id = str(uuid.uuid4())
    jobs[fix_job_id] = {
        "id":         fix_job_id,
        "type":       "pr_fix",
        "status":     "running",
        "repo":       repo,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result":     None,
        "error":      None,
    }

    logger.info("[fix_request] Starting fix for %s#%d via job %s", repo, pr_number, fix_job_id)

    from agent.review_graph import run_pr_fix
    fix_result = await run_pr_fix(
        repo_name=repo,
        pr_number=pr_number,
        pr_branch=pr_branch,
        review_result=review_result,
        rsi_context_str=rsi_context_str,
        changed_files=changed_files,
        pr_diff=pr_diff,
        github_token=github_token,
        emit_event=_emit_event,
        job_id=fix_job_id,
    )

    fix_pr_url = fix_result.get("final_pr_url", "")
    jobs[fix_job_id]["status"] = "pr_opened" if fix_pr_url else "failed"
    jobs[fix_job_id]["result"] = fix_result
    jobs[fix_job_id]["error"]  = fix_result.get("error", "") if not fix_pr_url else None

    if fix_pr_url:
        _emit_event("job_completed", {"job_id": fix_job_id, "pr_url": fix_pr_url})
    else:
        _emit_event("job_failed", {"job_id": fix_job_id, "error": fix_result.get("error", "")})

    return fix_pr_url


async def _handle_pull_request(payload: dict) -> None:
    """Run PR review when a PR is opened/updated.

    Score thresholds (from settings):
    - >= auto_merge_threshold : success commit status, no Telegram
    - >= manual_threshold     : success commit status + Telegram approval buttons
    - < manual_threshold      : failure commit status + Telegram 'Request Fix' button
                                (fix is NOT auto-triggered — user decides)

    RSI is NOT updated here — it reflects main-branch state only.
    """
    repo         = payload.get("repository", {}).get("full_name", "unknown")
    pr           = payload.get("pull_request", {})
    pr_number    = pr.get("number")
    head_sha     = pr.get("head", {}).get("sha", "")
    github_token = await get_token_for_repo(repo) or get_settings().github_token

    if head_sha:
        dedup_key = f"{repo}#{pr_number}@{head_sha}"
        if dedup_key in _reviewed_shas:
            logger.info("[pr_review] Already reviewed %s — skipping duplicate", dedup_key)
            return
        _reviewed_shas.add(dedup_key)

    from rsi import db
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        rsi_exists = await conn.fetchrow(
            "SELECT 1 FROM rsi_file_map WHERE repo_id=$1 LIMIT 1", repo
        )

    if not rsi_exists:
        logger.info("[pr_review] No RSI for %s — skipping until cold-start runs", repo)
        _emit_event("pr_review_skipped", {"repo": repo, "pr": pr_number, "reason": "no_rsi_data"})
        return

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "id":         job_id,
        "type":       "pr_review",
        "status":     "running",
        "repo":       repo,
        "branch":     pr.get("head", {}).get("ref", ""),
        "pr_number":  pr_number,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result":     None,
        "error":      None,
    }

    try:
        from agent.review_graph import run_pr_review
        _emit_event("job_started", {"job_id": job_id, "repo": repo, "type": "pr_review"})

        if head_sha:
            await _post_commit_status(repo, head_sha, "pending", github_token,
                                      "DevOps Agent reviewing…")

        review_result = await run_pr_review(
            repo_name=repo,
            pr_number=pr_number,
            github_token=github_token,
            emit_event=_emit_event,
            job_id=job_id,
        )

        # Store full review state so _handle_fix_request can retrieve it later
        jobs[job_id]["status"] = "review_posted"
        jobs[job_id]["result"] = review_result

        _emit_event("job_completed", {
            "job_id":     job_id,
            "review_url": review_result.get("comment_url", ""),
        })

        _rv          = review_result.get("review_result", {})
        score        = int(_rv.get("score", 0))
        label        = _rv.get("score_label", "")
        merge_rec    = _rv.get("merge_recommendation", "block")
        findings     = _rv.get("findings", _rv.get("file_reviews", []))
        comment_url  = review_result.get("comment_url", "")
        settings     = get_settings()

        logger.info("[pr_review] %s#%d — score=%d  label=%s  recommendation=%s",
                    repo, pr_number, score, label, merge_rec)

        # ── Commit status ──────────────────────────────────
        if head_sha:
            if score >= settings.pr_review_auto_merge_threshold:
                await _post_commit_status(repo, head_sha, "success", github_token,
                                          f"Score {score}/100 — {label}")
            elif score >= settings.pr_review_manual_threshold:
                await _post_commit_status(repo, head_sha, "success", github_token,
                                          f"Score {score}/100 — needs review before merge")
            else:
                await _post_commit_status(repo, head_sha, "failure", github_token,
                                          f"Score {score}/100 — quality gate failed")

        # ── Telegram notification ──────────────────────────
        chat_id  = await _get_telegram_chat_id(repo)
        chat_ids = [chat_id] if chat_id else []

        if score >= settings.pr_review_auto_merge_threshold:
            # Clean pass — no action needed from user
            pass

        elif score >= settings.pr_review_manual_threshold:
            # Decent score — let user approve/reject the PR itself
            from messages import ci_completed_approval
            msg = ci_completed_approval(repo, job_id, pr.get("html_url", ""))
            if telegram_notifier and chat_ids:
                await telegram_notifier.notify_pr_approval(msg, repo, pr_number, chat_ids=chat_ids)

        else:
            # Low score — send "Request Fix" button; do NOT auto-trigger fix
            from messages import pr_review_score
            msg = pr_review_score(repo, pr_number, score, label, comment_url,
                                  merge_recommendation=merge_rec, top_findings=findings[:3])
            if telegram_notifier and chat_ids:
                await telegram_notifier.notify_review_fix_request(
                    msg, repo, pr_number, job_id, chat_ids=chat_ids,
                )
            else:
                await _notify_telegram(msg, repo=repo)

    except Exception as exc:
        logger.exception("[pr_review] Failed for %s#%s", repo, pr_number)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"]  = str(exc)
        _emit_event("job_failed", {"job_id": job_id, "error": str(exc)})

        try:
            if head_sha:
                await _post_commit_status(repo, head_sha, "failure", github_token,
                                          "PR review pipeline failed")
        except Exception:
            pass

        from messages import pr_failed
        await _notify_telegram(pr_failed(repo, pr_number, str(exc)), repo=repo)


async def _handle_installation(payload: dict) -> None:
    """Cold-start RSI ingestion when a repo is first connected."""
    repos = payload.get("repositories", payload.get("repositories_added", []))
    for repo_info in repos:
        repo_name = repo_info.get("full_name", repo_info.get("name", "unknown"))
        github_token = await get_token_for_repo(repo_name) or get_settings().github_token
        _emit_event("cold_start_started", {"repo": repo_name})
        try:
            from rsi.builder import cold_start_build
            await cold_start_build(repo_name, github_token=github_token)
            _emit_event("cold_start_completed", {"repo": repo_name})
        except Exception as e:
            logger.exception("Cold start failed for %s", repo_name)
            _emit_event("cold_start_failed", {"repo": repo_name, "error": str(e)})


async def _handle_installation_removed(payload: dict) -> None:
    """B31: clean up RSI data when repos are removed from the GitHub App."""
    repos = payload.get("repositories_removed", [])
    for repo_info in repos:
        repo_name = repo_info.get("full_name", repo_info.get("name", "unknown"))
        logger.info("Removing RSI data for uninstalled repo %s", repo_name)
        try:
            from rsi import db as rsi_db
            await rsi_db.delete_rsi_for_repo(repo_name)
            _emit_event("rsi_removed", {"repo": repo_name})
        except Exception as e:
            logger.exception("Failed to remove RSI data for %s", repo_name)


# ─────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "DevOps Agent API is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/webhooks/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive GitHub webhook events.
    Verifies HMAC-SHA256 signature, then dispatches to the correct handler.
    """
    settings = get_settings()

    # ── Verify signature ────────────────────────────────
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not _verify_signature(body, signature, settings.github_webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # ── Parse event ─────────────────────────────────────
    event_type = request.headers.get("X-GitHub-Event", "")
    # B30: return 400 on malformed JSON instead of letting it raise a 500
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info("Webhook received: event=%s action=%s", event_type, payload.get("action", ""))

    # ── Dispatch ────────────────────────────────────────
    if event_type == "workflow_run" and payload.get("action") == "completed":
        conclusion = payload.get("workflow_run", {}).get("conclusion")
        head_branch = payload.get("workflow_run", {}).get("head_branch") or ""
        
        if head_branch.startswith("devops-agent/"):
            logger.info("Skipping CI failure for agent branch: %s", head_branch)
            return {"status": "ignored", "event": event_type, "reason": "agent branch"}

        if conclusion == "failure":
            job_id = str(uuid.uuid4())
            jobs[job_id] = {
                "id": job_id,
                "type": "ci_failure",
                "status": "pending",
                "repo": payload.get("repository", {}).get("full_name"),
                "branch": payload.get("workflow_run", {}).get("head_branch"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "result": None,
                "error": None,
            }
            background_tasks.add_task(_handle_ci_failure, payload, job_id)
            _emit_event("webhook_received", {
                "event": "ci_failure",
                "repo": payload.get("repository", {}).get("full_name"),
                "job_id": job_id,
            })
            return {"status": "accepted", "job_id": job_id}

    elif event_type == "push":
        ref = payload.get("ref", "")
        # L5: Only accept pushes to the repository's default branch for RSI updates.
        # This prevents the agent's own fix branches from triggering redundant background indexing.
        if ref.startswith("refs/heads/"):
            branch_name = ref.removeprefix("refs/heads/")
            default_branch = payload.get("repository", {}).get("default_branch", "main")
            
            if branch_name != default_branch:
                logger.info("Skipping RSI delta update for non-default branch: %s", branch_name)
                return {"status": "ignored", "event": event_type, "reason": "non-default branch"}

            background_tasks.add_task(_handle_push_to_main, payload)
            _emit_event("webhook_received", {
                "event": "push",
                "branch": branch_name,
                "repo": payload.get("repository", {}).get("full_name"),
            })
            return {"status": "accepted", "action": "rsi_delta_update"}

    elif event_type == "pull_request":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        base_ref = pr.get("base", {}).get("ref", "")
        head_ref = pr.get("head", {}).get("ref", "")
        repo_name = payload.get("repository", {}).get("full_name", "unknown")

        if head_ref.startswith("devops-agent/"):
            if action == "closed" and pr.get("merged", False) and head_ref.startswith("devops-agent/fix-"):
                background_tasks.add_task(_handle_merged_fix_pr, payload)
                _emit_event("webhook_received", {
                    "event": "fix_pr_merged",
                    "repo": repo_name,
                    "pr_number": pr.get("number"),
                })
                return {"status": "accepted", "action": "memory_store"}
            
            logger.info("Skipping PR webhook for agent branch: %s", head_ref)
            return {"status": "ignored", "event": event_type, "reason": "agent branch"}

        default_branch = payload.get("repository", {}).get("default_branch", "main")
        if base_ref == default_branch:
            pr_number = pr.get("number", 0)
            is_open_action = action in ("opened", "synchronize", "reopened")
            
            msg = pr_main_update(
                repo=repo_name,
                pr_number=pr_number,
                action=action,
                author=pr.get("user", {}).get("login", "unknown"),
                title=pr.get("title", "No title"),
                description=pr.get("body", "") or "",
                pr_url=pr.get("html_url", ""),
                needs_approval=is_open_action,
            )
            
            if telegram_notifier and is_open_action:
                chat_ids: list[int] = []
                chat_id = await _get_telegram_chat_id(repo_name)
                if chat_id:
                    chat_ids = [chat_id]
                    await telegram_notifier.notify_pr_approval(msg, repo_name, pr_number, chat_ids=chat_ids)
                else:
                    logger.debug("No Telegram chat_id for repo=%s — PR approval notification skipped", repo_name)
            else:
                await _notify_telegram(msg, repo=repo_name)

        if action in ("opened", "synchronize", "reopened"):
            background_tasks.add_task(_handle_pull_request, payload)
            _emit_event("webhook_received", {"event": "pull_request", "repo": payload.get("repository", {}).get("full_name")})
            return {"status": "accepted", "action": "pr_review"}

    elif event_type in ("installation", "installation_repositories"):
        action = payload.get("action", "")
        if action in ("created", "added"):
            background_tasks.add_task(_handle_installation, payload)
            _emit_event("webhook_received", {
                "event": "installation",
                "action": action,
            })
            return {"status": "accepted", "action": "cold_start_build"}
        # B31: clean up RSI data when repos are removed from the GitHub App
        elif action == "removed":
            background_tasks.add_task(_handle_installation_removed, payload)
            return {"status": "accepted", "action": "rsi_cleanup"}

    return {"status": "ignored", "event": event_type}


@app.post("/api/webhooks/telegram")
async def telegram_webhook(request: Request):
    """Receive Telegram updates in webhook mode."""
    if not telegram_notifier or not telegram_notifier.enabled:
        raise HTTPException(status_code=503, detail="Telegram notifier is not configured")

    payload = await request.json()
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

    try:
        await telegram_notifier.process_webhook_update(payload, secret)
    except TelegramAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return {"status": "accepted"}


@app.post("/api/repos/{repo_owner}/{repo_name}/initialize")
async def initialize_repo(repo_owner: str, repo_name: str, request: Request, background_tasks: BackgroundTasks):
    """
    Initialize a repository: run RSI cold-start AND create a GitHub webhook.
    The webhook subscribes to workflow_run (CI failures), pull_request, and push events.
    """
    from auth import get_session
    session = await get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    full_name = f"{repo_owner}/{repo_name}"
    user_repos = session.get("repos", [])

    # Verify the user actually has access to this repo
    has_access = any(r.get("full_name") == full_name for r in user_repos)
    if not has_access:
        raise HTTPException(status_code=403, detail="You do not have access to this repository")

    github_token = session.get("github_token")
    if not github_token:
        raise HTTPException(status_code=401, detail="Missing GitHub token in session")

    # 1. Create webhook (synchronous — fast API call)
    webhook_result = {}
    try:
        webhook_result = await create_webhook(full_name, github_token)
        _emit_event("webhook_created", {
            "repo": full_name,
            "webhook_id": webhook_result.get("webhook_id"),
            "created": webhook_result.get("created", False),
        })
        logger.info("Webhook for %s: %s", full_name, webhook_result)
    except ValueError as e:
        # WEBHOOK_BASE_URL not configured — warn but don't block cold-start
        logger.warning("Webhook creation skipped for %s: %s", full_name, e)
        webhook_result = {"error": str(e)}
    except Exception as e:
        logger.exception("Webhook creation failed for %s", full_name)
        webhook_result = {"error": str(e)}

    # 2. Cold-start RSI (background)
    _emit_event("cold_start_started", {"repo": full_name})

    async def _run_cold_start():
        try:
            from rsi.builder import cold_start_build
            await cold_start_build(full_name, github_token=github_token)
            _emit_event("cold_start_completed", {"repo": full_name})
        except Exception as e:
            logger.exception("Manual cold start failed for %s", full_name)
            _emit_event("cold_start_failed", {"repo": full_name, "error": str(e)})

    background_tasks.add_task(_run_cold_start)
    return {
        "status": "accepted",
        "message": f"Initialization started for {full_name}",
        "webhook": webhook_result,
    }


@app.get("/api/jobs")
def list_jobs():
    """List all agent jobs, newest first."""
    sorted_jobs = sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)
    return {"jobs": sorted_jobs}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    """Get a single job by ID."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/events")
async def event_stream(request: Request):
    """
    Server-Sent Events endpoint.
    B36: replaced 1-second polling with asyncio.Queue so events are delivered
    immediately when emitted. Each connected client gets its own queue.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_queues.add(q)

    async def _generate() -> AsyncGenerator[dict, None]:
        try:
            # Replay existing log so a freshly connected client sees history
            for event in list(event_log):
                yield {"event": event["type"], "data": json.dumps(event)}

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield {"event": event["type"], "data": json.dumps(event)}
                except asyncio.TimeoutError:
                    # Send a keep-alive comment so the connection stays open
                    yield {"comment": "keepalive"}
        finally:
            _sse_queues.discard(q)

    return EventSourceResponse(_generate())


# ─────────────────────────────────────────────────────────
# Webhook URL Settings
# ─────────────────────────────────────────────────────────

@app.get("/api/settings/webhook-url")
async def get_webhook_url(request: Request):
    """Return the currently configured webhook base URL."""
    from auth import get_session
    session = await get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    settings = get_settings()
    return {"webhook_base_url": settings.webhook_base_url}


@app.post("/api/settings/webhook-url")
async def set_webhook_url(request: Request):
    """
    Update the webhook base URL at runtime (e.g. after starting ngrok).
    Persists to .env and clears the settings cache.
    NOTE: In a multi-user deployment this should be restricted to admin users.
    For now all authenticated users can change it, but every change is audit-logged.
    """
    from auth import get_session
    session = await get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    body = await request.json()
    new_url = body.get("webhook_base_url", "").strip().rstrip("/")
    if not new_url:
        raise HTTPException(status_code=400, detail="webhook_base_url is required")
    if not new_url.startswith("https://"):
        raise HTTPException(status_code=400, detail="webhook_base_url must be an HTTPS URL")

    # S4: audit log — record who changed the URL
    caller_login = session.get("user_info", {}).get("login", "unknown")
    logger.info(
        "AUDIT: webhook_base_url changed to %s by user '%s'",
        new_url, caller_login,
    )

    # B10: use an absolute path derived from this file's location so the
    # correct .env is updated regardless of the process working directory
    env_path = Path(__file__).parent / ".env"
    lines = []
    found = False
    try:
        with open(env_path, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        pass

    new_lines = []
    for line in lines:
        if line.strip().startswith("WEBHOOK_BASE_URL"):
            new_lines.append(f"WEBHOOK_BASE_URL={new_url}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"WEBHOOK_BASE_URL={new_url}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)

    # Clear the cached settings so the new value is picked up
    get_settings.cache_clear()

    return {"status": "ok", "webhook_base_url": new_url}


# ─────────────────────────────────────────────────────────
# Monitored Repositories
# ─────────────────────────────────────────────────────────

@app.get("/api/repos/monitored")
async def get_monitored_repos(request: Request):
    """
    Return all repositories that are actively monitored:
    have RSI data in PostgreSQL AND a registered webhook.
    This endpoint is persistent — it survives server restarts.
    """
    from auth import get_session

    session = await get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        from rsi import db as rsi_db
        rsi_repos = await rsi_db.get_monitored_repos()
    except Exception as e:
        logger.warning("Failed to fetch monitored repos from RSI DB: %s", e)
        rsi_repos = []

    try:
        from state_store import get_webhook_ids_for_repos

        webhook_ids = await get_webhook_ids_for_repos(rsi_repos)
    except Exception as e:
        logger.warning("Failed to fetch webhook IDs for monitored repos: %s", e)
        webhook_ids = {}

    result = []
    for repo_id in rsi_repos:
        webhook_id = webhook_ids.get(repo_id)
        result.append({
            "full_name": repo_id,
            "has_rsi": True,
            "webhook_id": webhook_id,
            "webhook_active": webhook_id is not None,
        })

    return {"repos": result}


@app.delete("/api/repos/{repo_owner}/{repo_name}/monitoring")
async def remove_monitored_repo(repo_owner: str, repo_name: str, request: Request):
    """
    Remove a repository from monitoring:
    1. Delete the GitHub webhook
    2. Delete all RSI data from PostgreSQL
    3. Emit an rsi_removed event
    """
    from auth import get_session
    from webhook_manager import delete_webhook

    session = await get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    full_name = f"{repo_owner}/{repo_name}"
    github_token = session.get("github_token")
    if not github_token:
        raise HTTPException(status_code=401, detail="Missing GitHub token in session")

    errors = []

    # 1. Delete webhook from GitHub
    try:
        await delete_webhook(full_name, github_token)
        logger.info("Webhook deleted for %s", full_name)
    except Exception as e:
        logger.warning("Failed to delete webhook for %s: %s", full_name, e)
        errors.append(f"webhook: {e}")

    # 2. Delete RSI data from PostgreSQL
    try:
        from rsi import db as rsi_db
        await rsi_db.delete_rsi_for_repo(full_name)
        logger.info("RSI data deleted for %s", full_name)
    except Exception as e:
        logger.warning("Failed to delete RSI data for %s: %s", full_name, e)
        errors.append(f"rsi: {e}")

    # 3. Emit event so the frontend auto-refreshes
    _emit_event("rsi_removed", {"repo": full_name})

    if errors:
        return {
            "status": "partial",
            "message": f"Removed {full_name} with warnings",
            "errors": errors,
        }

    return {"status": "ok", "message": f"Removed {full_name} from monitoring"}


# ─────────────────────────────────────────────────────────
# Agent Memory — Merged Fix PR Handler
# ─────────────────────────────────────────────────────────

async def _handle_merged_fix_pr(payload: dict) -> None:
    """When a devops-agent/fix-* PR is merged, distill the fix
    knowledge and store it in the agent's episodic memory."""
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {}).get("full_name", "unknown")
    pr_number = pr.get("number")
    pr_url = pr.get("html_url", "")
    pr_title = pr.get("title", "")
    pr_body = pr.get("body", "") or ""
    github_token = await get_token_for_repo(repo) or get_settings().github_token

    logger.info("Merged agent fix PR #%s for %s — storing in memory", pr_number, repo)
    _emit_event("memory_store_started", {"repo": repo, "pr_number": pr_number})

    try:
        # 1. Recover the original CI error logs from the persistent agent_fix_jobs table.
        #    This survives server restarts — the in-memory jobs dict does not.
        from rsi.db import get_fix_job_by_pr_url
        fix_job = await get_fix_job_by_pr_url(pr_url)
        original_error_logs = fix_job["error_logs"] if fix_job else ""

        # Fallback: use PR title + body if no persistent record exists
        if not original_error_logs:
            original_error_logs = f"PR Title: {pr_title}\nPR Body: {pr_body[:2000]}"

        # 2. Fetch the list of changed files from the PR
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            owner, repo_name = repo.split("/")
            files_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/files",
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            files_changed = []
            if files_resp.status_code == 200:
                files_changed = [f["filename"] for f in files_resp.json()]

        # 3. Use the fast LLM to distill fix knowledge
        from agent.graph import get_fast_llm, _extract_json, _to_str
        from agent.prompts import MEMORY_SUMMARIZE_PROMPT
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = get_fast_llm()
        response = await llm.ainvoke([
            SystemMessage(content="You are a helpful assistant that outputs valid JSON only. No prose outside the JSON."),
            HumanMessage(content=MEMORY_SUMMARIZE_PROMPT.format(
                error_logs=original_error_logs[:4000],
                pr_title=pr_title,
                pr_body=pr_body[:3000],
                files_changed=", ".join(files_changed),
            )),
        ])

        raw = _to_str(response.content)
        import json as json_mod
        summary = json_mod.loads(_extract_json(raw))

        # 4. Store in memory
        from memory.store import store_memory
        memory_id = await store_memory(
            repo_id=repo,
            error_signature=summary.get("error_signature", pr_title),
            error_logs=original_error_logs[:10000],
            root_cause=summary.get("root_cause", ""),
            fix_summary=summary.get("fix_summary", ""),
            files_changed=files_changed,
            pr_url=pr_url,
            pr_number=pr_number,
            language=summary.get("language", ""),
        )

        logger.info("Stored fix memory #%d for %s PR #%s", memory_id, repo, pr_number)
        _emit_event("memory_stored", {
            "repo": repo,
            "pr_number": pr_number,
            "memory_id": memory_id,
            "error_signature": summary.get("error_signature", "")[:100],
        })

    except Exception as e:
        logger.exception("Failed to store fix memory for %s PR #%s", repo, pr_number)
        _emit_event("memory_store_failed", {
            "repo": repo,
            "pr_number": pr_number,
            "error": str(e),
        })


# ─────────────────────────────────────────────────────────
# Agent Memory API
# ─────────────────────────────────────────────────────────

@app.get("/api/memory")
async def get_memories(request: Request):
    """Return all stored fix memories."""
    from auth import get_session
    session = await get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from memory.store import get_all_memories
    memories = await get_all_memories(limit=50)
    return {"memories": memories}


@app.get("/api/memory/stats")
async def get_memory_stats_endpoint(request: Request):
    """Return memory bank statistics."""
    from auth import get_session
    session = await get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from memory.store import get_memory_stats
    stats = await get_memory_stats()
    return stats
