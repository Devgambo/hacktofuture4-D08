"""
PostgreSQL-backed persistence for auth sessions, repo token mappings,
and webhook registry records.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet

from config import get_settings
from rsi.db import get_pool

logger = logging.getLogger("devops_agent.state_store")


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _derive_fernet() -> Fernet:
    settings = get_settings()
    raw_key = settings.token_encryption_key.strip()
    if not raw_key:
        raw_key = "|".join(
            [
                settings.database_url,
                settings.github_client_secret,
                settings.github_webhook_secret,
            ]
        )
        logger.warning(
            "TOKEN_ENCRYPTION_KEY is not set; deriving a development key from existing secrets."
        )
    key_material = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key_material))


def encrypt_token(token: str) -> str:
    return _derive_fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token_ciphertext: str) -> str:
    return _derive_fernet().decrypt(token_ciphertext.encode("utf-8")).decode("utf-8")


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


async def upsert_session(
    session_id: str,
    github_token: str,
    user_info: dict[str, Any],
    repos: list[dict[str, Any]],
    expires_at: datetime,
) -> None:
    pool = await get_pool()
    token_ciphertext = encrypt_token(github_token)
    token_hash = _token_fingerprint(github_token)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO user_sessions (
                    session_id,
                    github_token_ciphertext,
                    github_token_hash,
                    user_info,
                    repos,
                    expires_at,
                    created_at,
                    updated_at
                )
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, now(), now())
                ON CONFLICT (session_id) DO UPDATE SET
                    github_token_ciphertext = EXCLUDED.github_token_ciphertext,
                    github_token_hash = EXCLUDED.github_token_hash,
                    user_info = EXCLUDED.user_info,
                    repos = EXCLUDED.repos,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = now()
                """,
                session_id,
                token_ciphertext,
                token_hash,
                json.dumps(user_info),
                json.dumps(repos),
                expires_at,
            )

            if repos:
                await conn.executemany(
                    """
                    INSERT INTO repo_credentials (
                        session_id,
                        repo_full_name,
                        github_token_ciphertext,
                        created_at,
                        updated_at
                    )
                    VALUES ($1, $2, $3, now(), now())
                    ON CONFLICT (session_id, repo_full_name) DO UPDATE SET
                        github_token_ciphertext = EXCLUDED.github_token_ciphertext,
                        updated_at = now()
                    """,
                    [
                        (session_id, repo["full_name"], token_ciphertext)
                        for repo in repos
                        if repo.get("full_name")
                    ],
                )


async def get_session(session_id: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT session_id, github_token_ciphertext, user_info, repos, expires_at
            FROM user_sessions
            WHERE session_id = $1
            """,
            session_id,
        )
        if not row:
            return None

        expires_at = row["expires_at"]
        if expires_at <= datetime.now(timezone.utc):
            await conn.execute("DELETE FROM user_sessions WHERE session_id = $1", session_id)
            return None

        user_info = _json_value(row["user_info"], {})
        repos = _json_value(row["repos"], [])
        return {
            "session_id": row["session_id"],
            "github_token": decrypt_token(row["github_token_ciphertext"]),
            "user_info": user_info,
            "repos": repos,
            "expires_at": expires_at,
        }


async def delete_session(session_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM user_sessions WHERE session_id = $1", session_id)


async def set_telegram_chat_id(session_id: str, chat_id: int) -> None:
    """Persist the Telegram chat_id for a user session so targeted notifications work."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_sessions SET telegram_chat_id = $1, updated_at = now() WHERE session_id = $2",
            chat_id,
            session_id,
        )
    logger.info("Telegram chat_id=%s linked to session %s", chat_id, session_id)


async def get_session_id_by_github_login(github_login: str) -> str | None:
    """Return the most-recent active session_id for a given GitHub username."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT session_id
            FROM user_sessions
            WHERE user_info->>'login' = $1
              AND expires_at > now()
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            github_login,
        )
    return str(row["session_id"]) if row else None


async def get_telegram_chat_id_for_repo(repo_full_name: str) -> int | None:
    """Return the Telegram chat_id for the owner of the given repo, or None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT us.telegram_chat_id
            FROM repo_credentials rc
            JOIN user_sessions us ON us.session_id = rc.session_id
            WHERE rc.repo_full_name = $1
              AND us.expires_at > now()
              AND us.telegram_chat_id IS NOT NULL
            ORDER BY rc.updated_at DESC
            LIMIT 1
            """,
            repo_full_name,
        )
    return int(row["telegram_chat_id"]) if row else None


async def get_token_for_repo(repo_full_name: str) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT rc.github_token_ciphertext
            FROM repo_credentials rc
            JOIN user_sessions us ON us.session_id = rc.session_id
            WHERE rc.repo_full_name = $1
              AND us.expires_at > now()
            ORDER BY rc.updated_at DESC, rc.created_at DESC
            LIMIT 1
            """,
            repo_full_name,
        )
    if not row:
        return None
    return decrypt_token(row["github_token_ciphertext"])


async def get_repo_names_for_token(github_token: str) -> list[str]:
    token_hash = _token_fingerprint(github_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT rc.repo_full_name
            FROM repo_credentials rc
            JOIN user_sessions us ON us.session_id = rc.session_id
            WHERE us.github_token_hash = $1
              AND us.expires_at > now()
            ORDER BY rc.repo_full_name
            """,
            token_hash,
        )
    return [row["repo_full_name"] for row in rows]


async def get_webhook_id(repo_full_name: str) -> int | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT webhook_id FROM repo_webhooks WHERE repo_full_name = $1",
            repo_full_name,
        )
    if not row:
        return None
    return int(row["webhook_id"])


async def upsert_webhook_id(repo_full_name: str, webhook_id: int, *, verified: bool = False) -> None:
    pool = await get_pool()
    verified_at = datetime.now(timezone.utc) if verified else None
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO repo_webhooks (repo_full_name, webhook_id, last_verified_at, created_at, updated_at)
            VALUES ($1, $2, $3, now(), now())
            ON CONFLICT (repo_full_name) DO UPDATE SET
                webhook_id = EXCLUDED.webhook_id,
                last_verified_at = EXCLUDED.last_verified_at,
                updated_at = now()
            """,
            repo_full_name,
            webhook_id,
            verified_at,
        )


async def delete_webhook_id(repo_full_name: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM repo_webhooks WHERE repo_full_name = $1", repo_full_name)


async def get_webhook_ids_for_repos(repo_full_names: list[str]) -> dict[str, int]:
    if not repo_full_names:
        return {}

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT repo_full_name, webhook_id
            FROM repo_webhooks
            WHERE repo_full_name = ANY($1)
            """,
            repo_full_names,
        )
    return {row["repo_full_name"]: int(row["webhook_id"]) for row in rows}
