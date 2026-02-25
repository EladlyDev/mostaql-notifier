"""Mostaql Notifier — Telegram Command Handlers.

Interactive commands via Telegram bot:
  /start — welcome message
  /status — system status
  /stats — today's statistics
  /pause — pause scanning
  /resume — resume scanning
  /last — last 5 analyzed jobs
  /force — force immediate scan cycle

Uses python-telegram-bot v22+ Application with polling.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import Application, CommandHandler as TgCmdHandler, ContextTypes

from src.database import queries
from src.notifier.formatters import _e, format_system_status
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.main import MostaqlNotifier

logger = get_logger(__name__)


class CommandHandler:
    """Telegram bot command handlers.

    Registers /commands with the Telegram bot Application,
    allowing the user to interact with the notifier via chat.

    Attributes:
        app: Reference to the MostaqlNotifier instance.
    """

    def __init__(self, app: "MostaqlNotifier") -> None:
        """Initialize with a reference to the main application.

        Args:
            app: Running MostaqlNotifier instance.
        """
        self.app = app

    def register(self, tg_app: Application) -> None:
        """Register all command handlers with the Telegram Application.

        Args:
            tg_app: python-telegram-bot Application instance.
        """
        tg_app.add_handler(TgCmdHandler("start", self._cmd_start))
        tg_app.add_handler(TgCmdHandler("status", self._cmd_status))
        tg_app.add_handler(TgCmdHandler("stats", self._cmd_stats))
        tg_app.add_handler(TgCmdHandler("pause", self._cmd_pause))
        tg_app.add_handler(TgCmdHandler("resume", self._cmd_resume))
        tg_app.add_handler(TgCmdHandler("last", self._cmd_last))
        tg_app.add_handler(TgCmdHandler("force", self._cmd_force))
        logger.info("Registered 7 Telegram commands")

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /start — show welcome message with available commands."""
        text = (
            "<b>🤖 Mostaql Notifier</b>\n"
            "\n"
            "مرحباً! أنا بوت مراقبة مستقل.\n"
            "أقوم برصد المشاريع الجديدة وإرسال تنبيهات ذكية.\n"
            "\n"
            "<b>الأوامر المتاحة:</b>\n"
            "/status — حالة النظام\n"
            "/stats — إحصائيات اليوم\n"
            "/pause — إيقاف الفحص مؤقتاً\n"
            "/resume — استئناف الفحص\n"
            "/last — آخر 5 مشاريع\n"
            "/force — فحص فوري\n"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /status — current system status."""
        app = self.app
        state = "⏸ متوقف مؤقتاً" if app.is_paused else "🟢 يعمل"

        lines = [
            "<b>🤖 حالة النظام</b>",
            "",
            f"📍 الحالة: {state}",
            f"⏱ التشغيل: {_e(app.uptime)}",
            f"🔄 الدورات: {app.cycle_count}",
            f"🕐 آخر فحص: {_e(app.last_cycle_time or 'لم يتم بعد')}",
            f"❌ أخطاء: {app.errors_count}",
        ]

        # DB stats if available
        if app.db:
            try:
                stats = await queries.get_today_stats(app.db)
                lines.extend([
                    "",
                    f"📌 مشاريع اليوم: <b>{stats.get('total_jobs', 0)}</b>",
                    f"⚡ تنبيهات فورية: <b>{stats.get('instant_count', 0)}</b>",
                    f"📋 ملخصات: <b>{stats.get('digest_count', 0)}</b>",
                ])
            except Exception:
                pass

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def _cmd_stats(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /stats — today's detailed statistics."""
        if not self.app.db:
            await update.message.reply_text("⚠️ قاعدة البيانات غير متصلة")
            return

        try:
            stats = await queries.get_today_stats(self.app.db)
            top_jobs = await queries.get_top_jobs_today(self.app.db, limit=5)

            from src.notifier.formatters import format_daily_report
            text = format_daily_report(stats, top_jobs)
            await update.message.reply_text(text, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {_e(str(e))}", parse_mode="HTML")

    async def _cmd_pause(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /pause — pause scanning."""
        self.app.pause()
        await update.message.reply_text(
            "⏸ <b>تم إيقاف الفحص مؤقتاً</b>\n\nاستخدم /resume للاستئناف",
            parse_mode="HTML",
        )

    async def _cmd_resume(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /resume — resume scanning."""
        self.app.resume()
        await update.message.reply_text(
            "▶️ <b>تم استئناف الفحص</b>",
            parse_mode="HTML",
        )

    async def _cmd_last(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /last — show last 5 analyzed jobs."""
        if not self.app.db:
            await update.message.reply_text("⚠️ قاعدة البيانات غير متصلة")
            return

        try:
            top = await queries.get_top_jobs_today(self.app.db, limit=5)
            if not top:
                await update.message.reply_text("لا توجد مشاريع محللة اليوم")
                return

            lines = ["<b>📋 آخر المشاريع المحللة:</b>", ""]
            for i, job in enumerate(top, 1):
                title = job.get("title", "?")[:40]
                url = job.get("url", "")
                score = job.get("overall_score", 0)
                rec = job.get("recommendation", "skip")

                rec_emoji = {"instant_alert": "⚡", "digest": "📋", "skip": "⏭️"}
                emoji = rec_emoji.get(rec, "❓")

                if url:
                    lines.append(
                        f'{emoji} {i}. <a href="{url}">{_e(title)}</a> — <b>{score}%</b>'
                    )
                else:
                    lines.append(f"{emoji} {i}. {_e(title)} — <b>{score}%</b>")

            await update.message.reply_text(
                "\n".join(lines), parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {_e(str(e))}", parse_mode="HTML")

    async def _cmd_force(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /force — trigger immediate scan cycle."""
        await update.message.reply_text(
            "🔄 <b>جاري بدء فحص فوري...</b>",
            parse_mode="HTML",
        )

        # Run in background so the command responds immediately
        asyncio.create_task(self._force_scan_bg(update))

    async def _force_scan_bg(self, update: Update) -> None:
        """Run a forced scan cycle and report back."""
        try:
            await self.app.run_scan_cycle()
            await update.message.reply_text(
                "✅ <b>تم الفحص الفوري بنجاح</b>",
                parse_mode="HTML",
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ خطأ في الفحص: {_e(str(e))}",
                parse_mode="HTML",
            )
