"""
GitHub Webhook Manager — create, delete, and list webhooks via the GitHub API.
Used to auto-provision webhooks when a user initializes a repo.
"""

import logging
from config import get_settings

import httpx

from state_store import (
    delete_webhook_id,
    get_repo_names_for_token,
    get_webhook_id as load_webhook_id,
    upsert_webhook_id,
)

logger = logging.getLogger("devops_agent.webhook_manager")

GITHUB_API = "https://api.github.com"


async def get_webhook_id(repo_full_name: str) -> int | None:
    """Return the stored webhook ID for a repo, if any."""
    return await load_webhook_id(repo_full_name)


async def create_webhook(
    repo_full_name: str,
    github_token: str,
) -> dict:
    """
    Create a GitHub webhook on the given repo.
    Subscribes to: workflow_run, pull_request, push.
    Returns {"webhook_id": <id>, "created": True} on success,
    or {"webhook_id": <id>, "created": False} if one already exists.
    """
    settings = get_settings()
    webhook_base_url = settings.webhook_base_url
    webhook_secret = settings.github_webhook_secret

    if not webhook_base_url:
        raise ValueError(
            "WEBHOOK_BASE_URL is not configured. "
            "Set it in Settings or your .env file (e.g. your ngrok URL)."
        )

    callback_url = f"{webhook_base_url.rstrip('/')}/api/webhooks/github"

    # Check if we already have a webhook for this repo
    existing_id = await load_webhook_id(repo_full_name)
    if existing_id:
        # Verify it still exists on GitHub
        exists = await _webhook_exists(repo_full_name, github_token, existing_id)
        if exists:
            logger.info("Webhook already exists for %s (id=%s)", repo_full_name, existing_id)
            await upsert_webhook_id(repo_full_name, existing_id, verified=True)
            return {"webhook_id": existing_id, "created": False}
        else:
            # Stale entry — remove it
            await delete_webhook_id(repo_full_name)

    # Also check GitHub for any webhook pointing to our URL (dedup)
    dup_id = await _find_existing_webhook(repo_full_name, github_token, callback_url)
    if dup_id:
        await upsert_webhook_id(repo_full_name, dup_id, verified=True)
        logger.info("Found existing webhook for %s on GitHub (id=%s)", repo_full_name, dup_id)
        return {"webhook_id": dup_id, "created": False}

    # Create new webhook
    owner, repo = repo_full_name.split("/")
    url = f"{GITHUB_API}/repos/{owner}/{repo}/hooks"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "name": "web",
        "active": True,
        "events": ["workflow_run", "pull_request", "push"],
        "config": {
            "url": callback_url,
            "content_type": "json",
            "secret": webhook_secret,
            "insecure_ssl": "0",
        },
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 422:
            # Hook already exists (GitHub returns 422 for duplicate hooks)
            logger.info("GitHub reports webhook already exists for %s", repo_full_name)
            dup_id = await _find_existing_webhook(repo_full_name, github_token, callback_url)
            if dup_id:
                await upsert_webhook_id(repo_full_name, dup_id, verified=True)
                return {"webhook_id": dup_id, "created": False}
            return {"webhook_id": None, "created": False}
        resp.raise_for_status()
        hook_data = resp.json()

    webhook_id = hook_data["id"]
    await upsert_webhook_id(repo_full_name, webhook_id, verified=True)

    logger.info("Created webhook for %s (id=%s)", repo_full_name, webhook_id)
    return {"webhook_id": webhook_id, "created": True}


async def delete_webhook(
    repo_full_name: str,
    github_token: str,
    webhook_id: int | None = None,
) -> bool:
    """
    Delete a GitHub webhook. If webhook_id is not provided, looks it up from the store.
    Returns True if deleted, False otherwise.
    """
    wh_id = webhook_id or await load_webhook_id(repo_full_name)
    if not wh_id:
        logger.info("No webhook to delete for %s", repo_full_name)
        return False

    owner, repo = repo_full_name.split("/")
    url = f"{GITHUB_API}/repos/{owner}/{repo}/hooks/{wh_id}"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(url, headers=headers)

    if resp.status_code in (204, 404):
        # 204 = deleted, 404 = already gone
        await delete_webhook_id(repo_full_name)
        logger.info("Deleted webhook for %s (id=%s)", repo_full_name, wh_id)
        return True

    logger.warning("Failed to delete webhook for %s: HTTP %s", repo_full_name, resp.status_code)
    return False


async def delete_all_webhooks_for_token(github_token: str) -> int:
    """
    Delete all webhooks we've created that are associated with repos
    accessible by this token. Used during logout cleanup.
    Returns the count of webhooks deleted.
    """
    # Find all repos associated with this token
    repos_for_token = await get_repo_names_for_token(github_token)
    deleted = 0

    for repo_name in repos_for_token:
        try:
            success = await delete_webhook(repo_name, github_token)
            if success:
                deleted += 1
        except Exception as e:
            logger.warning("Failed to cleanup webhook for %s: %s", repo_name, e)

    return deleted


async def _webhook_exists(
    repo_full_name: str, github_token: str, webhook_id: int
) -> bool:
    """Check if a specific webhook still exists on GitHub."""
    owner, repo = repo_full_name.split("/")
    url = f"{GITHUB_API}/repos/{owner}/{repo}/hooks/{webhook_id}"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)

    return resp.status_code == 200


async def _find_existing_webhook(
    repo_full_name: str, github_token: str, callback_url: str
) -> int | None:
    """Search for an existing webhook pointing to our callback URL."""
    owner, repo = repo_full_name.split("/")
    url = f"{GITHUB_API}/repos/{owner}/{repo}/hooks"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return None
        hooks = resp.json()

    for hook in hooks:
        config = hook.get("config", {})
        if config.get("url") == callback_url:
            return hook["id"]

    return None
