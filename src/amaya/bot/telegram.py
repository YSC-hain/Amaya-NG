from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

TextHandler = Callable[[str], Awaitable[str]]


@dataclass
class TelegramAdapter:
    token: str
    handle_text: TextHandler

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message:
            await update.message.reply_text(
                "Amaya-NG is running. Send me a message and I will echo it."
            )

    async def _on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message and update.message.text is not None:
            reply = await self.handle_text(update.message.text)
            if reply:
                await update.message.reply_text(reply)

    def run_polling(self) -> None:
        app = ApplicationBuilder().token(self.token).build()
        app.add_handler(CommandHandler("start", self._on_start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        app.run_polling()
