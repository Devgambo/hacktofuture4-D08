"""
Telegram bot integration powered by python-telegram-bot.
Provides webhook update handling and outbound notifications.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # pyright: ignore[reportMissingImports]
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes  # pyright: ignore[reportMissingImports]

logger = logging.getLogger("devops_agent.telegram")

_LINK_HELP = (
    "To receive targeted notifications, send:\n"
    "  /link <your-github-username>\n"
    "Example: /link octocat\n\n"
    "Your GitHub username is the one you used to log in to DevOps Agent."
)


class TelegramAuthError(Exception):
    """Raised when Telegram webhook auth is invalid."""


@dataclass
class TelegramNotifier:
    token: str
    webhook_secret: str = ""
    webhook_url: str = ""
    allowed_user_ids: list[int] = field(default_factory=list)

    _application: Application | None = None
    _started: bool = False
    # Registered by main.py — called when user clicks "Request Fix" after a low-score review
    _fix_request_callback: object = None   # async callable(repo, pr_number, job_id) -> str

    def register_fix_callback(self, callback) -> None:
        """Register the async callback invoked when user requests a PR fix via Telegram."""
        self._fix_request_callback = callback

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def start(self) -> None:
        """Initialize and start the Telegram application if enabled."""
        if not self.enabled:
            logger.info("Telegram notifier disabled (no TELEGRAM_BOT_TOKEN set)")
            return

        app: Application = Application.builder().token(self.token).build()
        self._application = app
        app.add_handler(CommandHandler("start", self._on_start))
        app.add_handler(CommandHandler("link", self._on_link))
        app.add_handler(CommandHandler("status", self._on_status))
        app.add_handler(CommandHandler("hello", self._on_hello))
        app.add_handler(CallbackQueryHandler(self._on_pr_action))

        await app.initialize()
        await app.start()

        if self.webhook_url:
            await app.bot.set_webhook(
                url=self.webhook_url,
                secret_token=self.webhook_secret or None,
                drop_pending_updates=False,
            )
            logger.info("Telegram webhook configured at %s", self.webhook_url)
        else:
            logger.warning(
                "TELEGRAM_WEBHOOK_URL is empty; Telegram updates cannot reach this service in webhook mode"
            )

        self._started = True
        logger.info("Telegram notifier started")

    async def stop(self) -> None:
        """Stop and shut down the Telegram application if it was started."""
        app = self._application
        if app is None:
            return

        try:
            if self.webhook_url:
                await app.bot.delete_webhook(drop_pending_updates=False)
            if self._started:
                await app.stop()
        finally:
            await app.shutdown()
            self._started = False
            logger.info("Telegram notifier stopped")

    async def process_webhook_update(
        self, payload: dict, secret_header: str | None
    ) -> None:
        """Validate and process an incoming Telegram webhook update."""
        app = self._application
        if app is None:
            raise RuntimeError("Telegram notifier is not initialized")

        if self.webhook_secret and secret_header != self.webhook_secret:
            raise TelegramAuthError("Invalid Telegram webhook secret")

        update = Update.de_json(payload, app.bot)
        if not update:
            return

        user_id = update.effective_user.id if update.effective_user else None
        logger.info("Received Telegram update from user_id=%s", user_id)
        # B6: removed duplicate allowlist check that was copy-pasted here
        if (
            user_id is not None
            and self.allowed_user_ids
            and user_id not in self.allowed_user_ids
        ):
            logger.warning(
                "Ignoring Telegram update from non-allowlisted user_id=%s", user_id
            )
            logger.info(
                "To allowlist this user, add %s to TELEGRAM_ALLOWED_USER_IDS in .env",
                user_id,
            )
            return

        await app.process_update(update)

    async def notify(self, text: str, *, chat_ids: list[int] | None = None) -> None:
        """Send a Telegram message to the given chat_ids.

        If *chat_ids* is provided and non-empty, the message is sent only to
        those IDs — enabling per-user targeted notifications.
        If *chat_ids* is None or empty, the message falls back to the static
        ``allowed_user_ids`` list (backwards-compatible for admin-level alerts).
        """
        app = self._application
        if app is None:
            return

        recipients = chat_ids if chat_ids else self.allowed_user_ids
        if not recipients:
            return

        for user_id in recipients:
            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                )
                logger.info("Telegram notification sent to chat_id=%s", user_id)
            except Exception:  # pragma: no cover - network and chat-level failures
                logger.exception(
                    "Failed to send Telegram notification to chat_id=%s", user_id
                )

    async def _on_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Acknowledge bot setup and prompt user to link their GitHub account."""
        if not update.effective_user or not update.message:
            return

        if (
            self.allowed_user_ids
            and update.effective_user.id not in self.allowed_user_ids
        ):
            return

        await update.message.reply_text(
            "DevOps Agent bot is connected.\n\n" + _LINK_HELP
        )

    async def _on_link(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Link this Telegram chat to a GitHub user session via /link <github_username>."""
        if not update.effective_user or not update.message:
            return

        if (
            self.allowed_user_ids
            and update.effective_user.id not in self.allowed_user_ids
        ):
            await update.message.reply_text(
                "You are not authorized to use this bot."
            )
            return

        args = (context.args or [])
        if not args:
            await update.message.reply_text(
                "Usage: /link <github-username>\nExample: /link octocat"
            )
            return

        github_login = args[0].strip().lstrip("@")
        chat_id = update.effective_user.id

        try:
            from state_store import get_session_id_by_github_login, set_telegram_chat_id

            session_id = await get_session_id_by_github_login(github_login)
            if not session_id:
                await update.message.reply_text(
                    f"No active session found for GitHub user '{github_login}'.\n"
                    "Make sure you are logged in to DevOps Agent first."
                )
                return

            await set_telegram_chat_id(session_id, chat_id)
            logger.info(
                "Linked Telegram chat_id=%s to GitHub login='%s' (session=%s)",
                chat_id, github_login, session_id,
            )
            await update.message.reply_text(
                f"\u2705 Linked! Notifications for '{github_login}' will now be sent here."
            )
        except Exception:
            logger.exception(
                "Failed to link Telegram chat_id=%s to GitHub login='%s'",
                chat_id, github_login,
            )
            await update.message.reply_text(
                "Something went wrong while linking your account. Please try again later."
            )

    async def _on_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Simple health response for allowlisted users."""
        if not update.effective_user or not update.message:
            return

        if (
            self.allowed_user_ids
            and update.effective_user.id not in self.allowed_user_ids
        ):
            return

        await update.message.reply_text("DevOps Agent notifier is running.")

    async def _on_hello(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Simple hello response for allowlisted users."""
        if not update.effective_user or not update.message:
            return

        if (
            self.allowed_user_ids
            and update.effective_user.id not in self.allowed_user_ids
        ):
            return

        await update.message.reply_text(
            "Hello! I'm running and ready to receive notifications."
        )

    async def notify_pr_approval(
        self, text: str, repo: str, pr_number: int, *, chat_ids: list[int] | None = None
    ) -> None:
        """Send a message with inline Accept/Reject buttons for a PR."""
        app = self._application
        if app is None:
            return

        recipients = chat_ids if chat_ids else self.allowed_user_ids
        if not recipients:
            return

        keyboard = [
            [
                InlineKeyboardButton("✅ Merge", callback_data=f"pr_merge:{repo}:{pr_number}"),
                InlineKeyboardButton("❌ Close", callback_data=f"pr_close:{repo}:{pr_number}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        for user_id in recipients:
            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
                logger.info("PR approval notification sent to chat_id=%s for %s#%s", user_id, repo, pr_number)
            except Exception:
                logger.exception("Failed to send PR approval notification to chat_id=%s", user_id)

    async def notify_review_fix_request(
        self, text: str, repo: str, pr_number: int, job_id: str,
        *, chat_ids: list[int] | None = None,
    ) -> None:
        """Send review result with a 'Request Fix' button for low-score PRs."""
        app = self._application
        if app is None:
            return

        recipients = chat_ids if chat_ids else self.allowed_user_ids
        if not recipients:
            return

        keyboard = [[
            InlineKeyboardButton(
                "🔧 Request Fix",
                callback_data=f"review_fix:{job_id}",
            ),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        for user_id in recipients:
            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
                logger.info("Review fix-request button sent to chat_id=%s for %s#%s",
                            user_id, repo, pr_number)
            except Exception:
                logger.exception("Failed to send review fix-request to chat_id=%s", user_id)

    async def _on_pr_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline button presses for PR approve/reject/fix-request."""
        query = update.callback_query
        if not query or not update.effective_user:
            return

        user_id = update.effective_user.id
        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            await query.answer("You are not authorized.", show_alert=True)
            return

        await query.answer()

        data = query.data or ""

        # ── Review fix request ───────────────────────────
        if data.startswith("review_fix:"):
            _, job_id = data.split(":", 1)
            
            if self._fix_request_callback is None:
                await query.edit_message_text(text="❌ Fix callback not configured.")
                return

            await query.edit_message_text(text="⏳ Generating fix PR...")
            try:
                fix_pr_url = await self._fix_request_callback(job_id)
                if fix_pr_url:
                    await query.edit_message_text(
                        text=f"✅ Fix PR opened: {fix_pr_url}",
                    )
                else:
                    await query.edit_message_text(text="⚠️ Fix agent ran but no PR was opened.")
            except Exception as exc:
                logger.exception("Fix request callback failed.")
                await query.edit_message_text(text=f"❌ Fix failed: {exc}")
            return

        # ── PR merge / close ─────────────────────────────
        if not data.startswith(("pr_merge:", "pr_close:")):
            return

        action, rest = data.split(":", 1)
        try:
            repo, pr_number_str = rest.rsplit(":", 1)
            pr_number = int(pr_number_str)
        except ValueError:
            await query.edit_message_text(text="❌ Invalid PR data in button callback.")
            return

        from state_store import get_token_for_repo
        github_token = await get_token_for_repo(repo)
        if not github_token:
            from config import get_settings
            github_token = get_settings().github_token

        if not github_token:
            await query.edit_message_text(text="❌ No GitHub token available to perform this action.")
            return

        import httpx
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        api_base = f"https://api.github.com/repos/{repo}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                if action == "pr_merge":
                    resp = await client.put(f"{api_base}/pulls/{pr_number}/merge", headers=headers)
                    if resp.status_code in (200, 201, 204):
                        await query.edit_message_text(
                            text=f"✅ *PR \\#{pr_number} Merged* successfully\\!",
                            parse_mode="MarkdownV2",
                        )
                    else:
                        err = resp.json().get("message", "Unknown error")
                        await query.edit_message_text(
                            text=f"❌ *Failed to merge PR \\#{pr_number}*: {err}",
                            parse_mode="MarkdownV2",
                        )
                elif action == "pr_close":
                    resp = await client.patch(f"{api_base}/pulls/{pr_number}", headers=headers,
                                              json={"state": "closed"})
                    if resp.status_code == 200:
                        await query.edit_message_text(
                            text=f"❌ *PR \\#{pr_number} Closed* successfully\\.",
                            parse_mode="MarkdownV2",
                        )
                    else:
                        err = resp.json().get("message", "Unknown error")
                        await query.edit_message_text(
                            text=f"❌ *Failed to close PR \\#{pr_number}*: {err}",
                            parse_mode="MarkdownV2",
                        )
        except Exception as e:
            logger.exception("GitHub API error processing PR action %s for repo %s", action, repo)
            await query.edit_message_text(text=f"❌ **Error performing action:** {e}")
