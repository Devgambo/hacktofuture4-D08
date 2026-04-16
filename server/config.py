"""
Centralised configuration loaded from environment variables.
Uses pydantic-settings so .env files are picked up automatically.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── OpenAI ──────────────────────────────────────
    openai_api_key: str = ""

    # ── Model IDs ────────────────────
    # Coding / fix generation  →  gpt-4o
    coding_model_id: str = "gpt-4o"
    # Deep reasoning / PR review  →  gpt-4o-mini
    reasoning_model_id: str = "gpt-4o-mini"
    # Fast / cheap tasks (symbol extraction)  →  gpt-4o-mini
    fast_model_id: str = "gpt-4o-mini"

    # ── GitHub OAuth ────────────────────────────────────
    github_client_id: str = ""
    github_client_secret: str = ""
    github_webhook_secret: str = ""
    github_token: str = ""  # fallback PAT (optional)

    # ── Webhook ─────────────────────────────────────────
    webhook_base_url: str = ""  # Public URL for webhook callbacks (e.g. ngrok)

    # ── Database ────────────────────────────────────────
    database_url: str = ""

    # ── Persistent token encryption ─────────────────────
    # Used to encrypt GitHub tokens stored in PostgreSQL.
    token_encryption_key: str = ""

    # ── App environment ─────────────────────────────────
    # Set to "production" to enable secure=True on session cookies (HTTPS only)
    app_env: str = "development"

    # ── Server ──────────────────────────────────────────
    log_level: str = "info"

    # ── PR Review pipeline thresholds ───────────────────
    pr_review_auto_merge_threshold: int = 75
    pr_review_manual_threshold: int = 50

    # ── Telegram Bot ────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_webhook_url: str = ""
    telegram_allowed_user_ids: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def telegram_allowed_user_id_list(self) -> list[int]:
        """Parse comma-separated TELEGRAM_ALLOWED_USER_IDS into integer IDs."""
        raw_ids = [chunk.strip() for chunk in self.telegram_allowed_user_ids.split(",") if chunk.strip()]
        parsed: list[int] = []
        for raw in raw_ids:
            try:
                parsed.append(int(raw))
            except ValueError:
                continue
        return parsed

    @property
    def is_production(self) -> bool:
        """True when running in a production environment."""
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
