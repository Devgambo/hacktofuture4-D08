"""
GitHub OAuth authentication flow.
Handles login, callback, session management, and user info.
"""

import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import RedirectResponse

from config import get_settings

from state_store import (
    delete_session,
    get_session as load_session,
    get_token_for_repo as load_repo_token,
    upsert_session,
)
logger = logging.getLogger("devops_agent.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


# S2: Pending OAuth state tokens — maps state → expiry timestamp (10-min TTL)
_pending_states: dict[str, float] = {}
_STATE_TTL_SECONDS = 600  # 10 minutes

SESSION_COOKIE = "devops_session"
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_REPOS_URL = "https://api.github.com/user/repos"

# OAuth scopes: repo (full repo access) + workflow (actions access)
OAUTH_SCOPES = "repo workflow admin:repo_hook"

# Max pages to fetch for repo listing (100 repos/page → up to 1000 repos)
_REPO_MAX_PAGES = 10


def _cleanup_expired_states() -> None:
    """Remove expired OAuth state tokens to prevent unbounded growth."""
    now = time.monotonic()
    expired = [s for s, exp in _pending_states.items() if now > exp]
    for s in expired:
        del _pending_states[s]


async def get_session(request: Request) -> dict | None:
    """Extract the session from the request cookie."""
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None
    return await load_session(session_id)


async def get_token_for_repo(repo_full_name: str) -> str | None:
    """Look up the stored OAuth token for a given repo."""
    return await load_repo_token(repo_full_name)


@router.get("/github")
async def github_login():
    """Redirect user to GitHub OAuth authorization page."""
    settings = get_settings()
    # S2: generate and store state server-side for CSRF protection
    state = secrets.token_urlsafe(32)
    _cleanup_expired_states()
    _pending_states[state] = time.monotonic() + _STATE_TTL_SECONDS

    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": "http://localhost:8000/api/auth/callback",
        "scope": OAUTH_SCOPES,
        "state": state,
    }

    return RedirectResponse(url=f"{GITHUB_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def github_callback(code: str, state: str | None = None):
    """
    Handle the OAuth callback from GitHub.
    Exchange the code for an access token, fetch user info,
    store session, and redirect to the frontend.
    """
    settings = get_settings()

    # S2: verify state to prevent CSRF attacks
    _cleanup_expired_states()
    if not state or state not in _pending_states:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state — possible CSRF attempt. Please try logging in again.",
        )
    now = time.monotonic()
    if now > _pending_states[state]:
        del _pending_states[state]
        raise HTTPException(
            status_code=400,
            detail="OAuth state token expired. Please try logging in again.",
        )
    # Consume the state (one-time use)
    del _pending_states[state]

    # 1. Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        logger.error("OAuth token exchange failed: %s", token_data)
        raise HTTPException(status_code=400, detail="Failed to get access token from GitHub")

    # 2. Fetch user profile
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        user_resp.raise_for_status()
        user_info = user_resp.json()

    # 3. Fetch user's repos with pagination (L6: was only fetching first 100)
    repos: list[dict] = []
    async with httpx.AsyncClient() as client:
        for page in range(1, _REPO_MAX_PAGES + 1):
            repos_resp = await client.get(
                GITHUB_REPOS_URL,
                params={"per_page": 100, "sort": "updated", "page": page},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            repos_resp.raise_for_status()
            page_repos = repos_resp.json()
            if not page_repos:
                break  # No more pages
            repos.extend(page_repos)
            if len(page_repos) < 100:
                break  # Last page (partial)

    # 4. Create session
    session_id = str(uuid.uuid4())
    session_repos = [
        {
            "full_name": r["full_name"],
            "private": r["private"],
            "html_url": r["html_url"],
            "description": r.get("description", ""),
            "language": r.get("language", ""),
            "updated_at": r.get("updated_at", ""),
        }
        for r in repos
    ]

    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await upsert_session(
        session_id=session_id,
        github_token=access_token,
        user_info={
            "login": user_info.get("login"),
            "avatar_url": user_info.get("avatar_url"),
            "name": user_info.get("name"),
            "html_url": user_info.get("html_url"),
        },
        repos=session_repos,
        expires_at=expires_at,
    )

    logger.info("User %s logged in (session %s, %d repos)", user_info.get("login"), session_id, len(repos))

    # 5. Set cookie and redirect to frontend
    response = RedirectResponse(url="http://localhost:5173/home", status_code=302)
    # S5: secure=True in production (HTTPS), False for localhost dev
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,  # 7 days
        secure=settings.is_production,
    )
    return response


@router.get("/me")
async def get_current_user(request: Request):
    """Return the current logged-in user's info."""
    session = await get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return {
        "user": session["user_info"],
        "repos": session.get("repos", []),
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Clear the session, cleanup webhooks, and delete cookie."""
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        session = await load_session(session_id)
    else:
        session = None

    if session:
        token = session.get("github_token")
        if token:
            # Cleanup webhooks we created for this user's repos
            try:
                from webhook_manager import delete_all_webhooks_for_token
                deleted = await delete_all_webhooks_for_token(token)
                logger.info("Cleaned up %d webhooks on logout", deleted)
            except Exception as e:
                logger.warning("Webhook cleanup failed: %s", e)
        await delete_session(session_id)

    response = RedirectResponse(url="http://localhost:5173", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response
