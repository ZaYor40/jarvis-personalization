"""
Channel Telegram pour Jarvis.
Un seul utilisateur autorisé : TELEGRAM_OWNER_ID.
Tourne en background process asyncio.
"""
from __future__ import annotations

import os
import asyncio
from loguru import logger

try:
    from telegram import Update
    from telegram.ext import (
        Application, CommandHandler, MessageHandler,
        filters, ContextTypes
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


_telegram_instance: TelegramChannel | None = None


def get_telegram_channel() -> TelegramChannel | None:
    return _telegram_instance


class TelegramChannel:
    """
    Canal Telegram pour Jarvis.
    Reçoit les messages, les passe au gateway Jarvis,
    retourne la réponse.
    """

    def __init__(self, gateway):
        self._gateway = gateway
        self._token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._owner_id = int(os.getenv("TELEGRAM_OWNER_ID", "0"))
        self._app = None

    def _is_owner(self, update: Update) -> bool:
        """Vérifie que le message vient bien du propriétaire."""
        return update.effective_user.id == self._owner_id

    async def start(self) -> None:
        if not TELEGRAM_AVAILABLE:
            logger.warning("python-telegram-bot non installé — canal Telegram désactivé")
            return

        if not self._token:
            logger.warning("TELEGRAM_BOT_TOKEN absent — canal Telegram désactivé")
            return

        if not self._owner_id:
            logger.warning("TELEGRAM_OWNER_ID absent — canal Telegram désactivé")
            return

        self._app = Application.builder().token(self._token).build()

        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("initiatives", self._cmd_initiatives))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

        logger.info("Telegram bot démarré")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send_message(self, text: str) -> None:
        """Envoyer un message proactif à l'owner (notifications)."""
        if self._app and self._owner_id:
            await self._app.bot.send_message(
                chat_id=self._owner_id,
                text=text,
                parse_mode="Markdown"
            )

    # ── Handlers ──────────────────────────────────────────────────

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Message texte — passer à Jarvis et retourner la réponse."""
        if not self._is_owner(update):
            await update.message.reply_text("⛔ Accès non autorisé.")
            return

        user_text = update.message.text
        logger.info(f"[Telegram] Message reçu : {user_text[:60]}")

        await ctx.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )

        _, _route, response = await self._gateway.handle(
            user_text,
            stream=False,
        )

        if len(response) > 4000:
            response = response[:3990] + "\n\n_[réponse tronquée]_"

        await update.message.reply_text(response, parse_mode="Markdown")

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update):
            return
        await update.message.reply_text(
            "🤖 *Jarvis connecté.*\n\n"
            "Envoie-moi n'importe quel message ou utilise les commandes :\n"
            "/status — état du système\n"
            "/initiatives — tes initiatives en attente\n"
            "/help — toutes les commandes",
            parse_mode="Markdown"
        )

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update):
            return
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get("http://localhost:8000/api/health")
                health = r.json()
            checks = health.get("checks", {})
            lines = []
            for name, info in checks.items():
                emoji = "✅" if info["status"] == "ok" else "⚠️" if info["status"] == "warning" else "❌"
                lines.append(f"{emoji} *{name}* — {info['detail']}")
            text = "🖥 *Jarvis Doctor*\n\n" + "\n".join(lines)
        except Exception as e:
            text = f"❌ Impossible de joindre Jarvis : {e}"
        await update.message.reply_text(text, parse_mode="Markdown")

    async def _cmd_initiatives(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update):
            return
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get("http://localhost:8000/api/initiatives")
                data = r.json()
            initiatives = [i for i in data.get("initiatives", []) if i.get("status") == "pending"]
            if not initiatives:
                await update.message.reply_text("✅ Aucune initiative en attente.")
                return
            lines = [f"⚡ *{len(initiatives)} initiative(s) en attente*\n"]
            for ini in initiatives[:5]:
                priority = ini.get("priority", "")
                emoji = "🔴" if priority == "high" else "🟡" if priority == "medium" else "⚪"
                lines.append(f"{emoji} {ini.get('title', '?')}")
            if len(initiatives) > 5:
                lines.append(f"\n_+{len(initiatives)-5} autres — voir le Command Center_")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Erreur : {e}")

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update):
            return
        text = (
            "🤖 *Jarvis — Commandes Telegram*\n\n"
            "*/status* — état de tous les composants\n"
            "*/initiatives* — liste des initiatives en attente\n"
            "*/help* — cette aide\n\n"
            "*Message libre* — parle à Jarvis normalement :\n"
            "• _\"Quelle est la météo à Lyon ?\"\n"
            "• \"Lance le preset travail\"\n"
            "• \"Mets du Booba sur Spotify\"\n"
            "• \"Quelles sont mes tâches du jour ?\"\n"
            "• \"État de mon impression 3D ?\"_"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
