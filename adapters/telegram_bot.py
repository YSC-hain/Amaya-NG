# adapters/telegram_bot.py
"""
Telegram 平台适配器 —— 封装所有 Telegram 相关的交互逻辑。
"""
import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import config
from adapters.base import MessageSender
from core.agent import amaya
from utils.storage import get_pending_reminders_summary

logger = logging.getLogger("Amaya.Telegram")


# --- 权限控制 ---
def _is_authorized(chat_id: int) -> bool:
    if not config.OWNER_ID:
        logger.error("OWNER_ID 未配置，拒绝所有请求。")
        return False
    return str(chat_id) == str(config.OWNER_ID)


# --- Telegram MessageSender 实现 ---
class TelegramSender(MessageSender):
    """Telegram 消息发送器"""

    def __init__(self, bot):
        self.bot = bot

    async def send_text(self, text: str, parse_mode: Optional[str] = "Markdown") -> bool:
        if not config.OWNER_ID:
            logger.error("OWNER_ID 未配置，无法发送消息。")
            return False
        try:
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=text,
                parse_mode=parse_mode,
            )
            return True
        except Exception as e:
            logger.warning(f"{parse_mode} 发送失败，回退纯文本: {e}")
            try:
                await self.bot.send_message(chat_id=config.OWNER_ID, text=text)
                return True
            except Exception as fallback_err:
                logger.error(f"消息发送彻底失败: {fallback_err}")
                return False


# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not _is_authorized(chat_id):
        await update.message.reply_text("未授权。仅限 OWNER 使用。")
        return
    logger.info(f"User {user.first_name} started the bot. Chat ID: {chat_id}")
    await update.message.reply_text(
        f"你好，{user.first_name}。\n我是 Amaya 原型机。\nID: `{chat_id}`",
        parse_mode="Markdown",
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update.effective_chat.id):
        await update.message.reply_text("未授权。仅限 OWNER 使用。")
        return
    await update.message.reply_text("Pong! 系统在线。")


async def reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看挂起的提醒任务"""
    if not _is_authorized(update.effective_chat.id):
        await update.message.reply_text("未授权。仅限 OWNER 使用。")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    summary = get_pending_reminders_summary()
    keyboard = [
        [InlineKeyboardButton("刷新", callback_data="refresh_reminders")],
        [InlineKeyboardButton("关闭", callback_data="close_reminders")],
    ]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_authorized(query.from_user.id):
        await query.edit_message_text("未授权。")
        return
    if query.data == "refresh_reminders":
        summary = get_pending_reminders_summary()
        keyboard = [
            [InlineKeyboardButton("刷新", callback_data="refresh_reminders")],
            [InlineKeyboardButton("关闭", callback_data="close_reminders")],
        ]
        try:
            await query.edit_message_text(text=summary, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.debug(f"编辑消息未变更: {e}")
    elif query.data == "close_reminders":
        await query.delete_message()


async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id = update.effective_chat.id

    if not _is_authorized(chat_id):
        await update.message.reply_text("未授权。仅限 OWNER 使用。")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    response_text = await amaya.chat(user_text)
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    logger.info(f"Amaya 回复: {response_text[:50]}...")

    try:
        await update.message.reply_text(response_text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Markdown 发送失败，回退纯文本: {e}")
        try:
            await update.message.reply_text(response_text)
        except Exception as send_err:
            logger.error(f"消息发送彻底失败: {send_err}")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update.effective_chat.id):
        await update.message.reply_text("未授权。仅限 OWNER 使用。")
        return
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
    except Exception as e:
        logger.error(f"图片下载失败: {e}")
        await update.message.reply_text("抱歉，图片下载失败，请重试。")
        return

    caption = update.message.caption or "用户发来了一张图片"

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response_text = await amaya.chat(caption, image_bytes=bytes(image_bytes))

    try:
        await update.message.reply_text(response_text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Markdown 发送失败，回退纯文本: {e}")
        try:
            await update.message.reply_text(response_text)
        except Exception as send_err:
            logger.error(f"消息发送彻底失败: {send_err}")


def register_handlers(application):
    """注册所有 Telegram handlers"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("reminders", reminders))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))


def build_application(post_init=None, post_shutdown=None):
    """构建 Telegram Application 实例"""
    builder = ApplicationBuilder().token(config.TOKEN)
    if post_init:
        builder = builder.post_init(post_init)
    if post_shutdown:
        builder = builder.post_shutdown(post_shutdown)
    return builder.build()
