# adapters/telegram_bot.py
"""
Telegram 平台适配器 —— 封装所有 Telegram 相关的交互逻辑。
"""
import asyncio
import logging
from typing import Optional, List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.error import TelegramError

import config
from adapters.base import MessageSender
from core.agent import amaya
from utils.storage import get_pending_reminders_summary

logger = logging.getLogger("Amaya.Telegram")

# Telegram 消息长度限制
MAX_MESSAGE_LENGTH = 4096
ALLOWED_AUDIO_MIME = {"audio/ogg", "audio/webm", "audio/wav", "audio/flac", "audio/mp3", "audio/mpeg"}


# --- 工具函数 ---
def _split_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """将长消息按段落/换行智能分割，避免截断单词或句子。"""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # 优先在换行处分割
        split_pos = text.rfind("\n", 0, max_len)
        if split_pos == -1 or split_pos < max_len // 2:
            # 其次在空格处分割
            split_pos = text.rfind(" ", 0, max_len)
        if split_pos == -1 or split_pos < max_len // 2:
            # 强制截断
            split_pos = max_len

        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip()

    return chunks


def _ensure_supported_audio(audio_bytes: bytes, mime_type: str) -> Tuple[Optional[bytes], Optional[str]]:
    """仅做格式白名单检查，不依赖 ffmpeg。"""
    if mime_type in ALLOWED_AUDIO_MIME:
        return audio_bytes, mime_type
    return None, None


async def _send_with_fallback(message, text: str, parse_mode: str = "Markdown"):
    """发送消息，支持长消息分段 + 格式回退。"""
    chunks = _split_message(text)
    for i, chunk in enumerate(chunks):
        try:
            await message.reply_text(chunk, parse_mode=parse_mode)
        except TelegramError:
            # Markdown 失败时回退到纯文本
            try:
                await message.reply_text(chunk)
            except TelegramError as e:
                logger.error(f"消息分段 {i+1}/{len(chunks)} 发送失败: {e}")


# --- 权限控制 ---
def _is_authorized(chat_id: int) -> bool:
    if not config.OWNER_ID:
        logger.error("OWNER_ID 未配置，拒绝所有请求。")
        return False
    return str(chat_id) == str(config.OWNER_ID)


async def _typing_spinner(context: ContextTypes.DEFAULT_TYPE, chat_id: int, stop_event: asyncio.Event, interval: int = 4):
    """循环发送 typing，直至 stop_event 触发。"""
    try:
        while not stop_event.is_set():
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        return


# --- Telegram MessageSender 实现 ---
class TelegramSender(MessageSender):
    """Telegram 消息发送器"""

    def __init__(self, bot):
        self.bot = bot

    async def send_text(self, text: str, parse_mode: Optional[str] = "Markdown") -> bool:
        if not config.OWNER_ID:
            logger.error("OWNER_ID 未配置，无法发送消息。")
            return False

        chunks = _split_message(text)
        success = True
        for chunk in chunks:
            try:
                await self.bot.send_message(
                    chat_id=config.OWNER_ID,
                    text=chunk,
                    parse_mode=parse_mode,
                )
            except TelegramError:
                try:
                    await self.bot.send_message(chat_id=config.OWNER_ID, text=chunk)
                except TelegramError as e:
                    logger.error(f"消息发送失败: {e}")
                    success = False
        return success


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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示帮助信息"""
    if not _is_authorized(update.effective_chat.id):
        await update.message.reply_text("未授权。仅限 OWNER 使用。")
        return
    help_text = (
        "*Amaya 使用指南*\n\n"
        "  *日常对话* - 直接发送消息即可\n"
        "  *图片理解* - 发送图片并附带说明\n"
        "  *语音消息* - 发送语音，我会理解内容\n\n"
        "*可用命令:*\n"
        "/start - 查看 Bot 信息\n"
        "/ping - 检查系统状态\n"
        "/reminders - 查看待执行的提醒\n"
        "/help - 显示此帮助\n\n"
        "*提醒示例:*\n"
        "• \"10分钟后提醒我喝水\"\n"
        "• \"明天早上8点叫我起床\""
    )  # ToDo
    await update.message.reply_text(help_text, parse_mode="Markdown")


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

    stop_event = asyncio.Event()
    spinner = asyncio.create_task(_typing_spinner(context, chat_id, stop_event))
    try:
        response_text = await amaya.chat(user_text)
    finally:
        stop_event.set()
        await spinner

    logger.info(f"Amaya 回复: {response_text[:50]}...")
    await _send_with_fallback(update.message, response_text)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update.effective_chat.id):
        await update.message.reply_text("未授权。仅限 OWNER 使用。")
        return

    chat_id = update.effective_chat.id
    stop_event = asyncio.Event()
    spinner = asyncio.create_task(_typing_spinner(context, chat_id, stop_event))

    response_text = None
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        caption = update.message.caption or "用户发来了一张图片"
        response_text = await amaya.chat(caption, image_bytes=bytes(image_bytes))
    except Exception as e:
        logger.error(f"图片处理失败: {e}")
        await update.message.reply_text("抱歉，图片处理失败，请重试。")
    finally:
        stop_event.set()
        await spinner

    if response_text:
        await _send_with_fallback(update.message, response_text)


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理语音消息（下载 OGG/OPUS 并传递给 Gemini）。"""
    if not _is_authorized(update.effective_chat.id):
        await update.message.reply_text("未授权。仅限 OWNER 使用。")
        return

    voice = update.message.voice
    if not voice:
        await update.message.reply_text("未找到语音内容，请重试。")
        return

    chat_id = update.effective_chat.id
    stop_event = asyncio.Event()
    spinner = asyncio.create_task(_typing_spinner(context, chat_id, stop_event))

    response_text = None
    try:
        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        mime_type = getattr(voice, "mime_type", None) or "audio/ogg"
        audio_bytes, mime_type = _ensure_supported_audio(bytes(audio_bytes), mime_type)
        if audio_bytes is None:
            await update.message.reply_text("当前语音格式不受支持，请以 OGG/OPUS/WEBM/WAV 重新发送。")
        else:
            user_hint = "[语音消息] 用户发来了一段语音，请结合上下文提炼关键内容进行回应。"
            response_text = await amaya.chat(user_hint, audio_bytes=audio_bytes, audio_mime=mime_type)
    except TelegramError as e:
        logger.error(f"语音下载失败: {e}")
        await update.message.reply_text(f"下载语音失败: {e}")
    except Exception as e:
        logger.error(f"语音处理失败: {e}")
        await update.message.reply_text("抱歉，语音处理失败，请重试。")
    finally:
        stop_event.set()
        await spinner

    if response_text:
        await _send_with_fallback(update.message, response_text)


def register_handlers(application):
    """注册所有 Telegram handlers"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reminders", reminders))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.VOICE, voice_handler))


def build_application(post_init=None, post_shutdown=None):
    """构建 Telegram Application 实例"""
    builder = ApplicationBuilder().token(config.TOKEN)
    if post_init:
        builder = builder.post_init(post_init)
    if post_shutdown:
        builder = builder.post_shutdown(post_shutdown)
    return builder.build()
