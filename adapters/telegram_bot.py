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
from telegram.error import TelegramError, NetworkError

import config
from adapters.base import MessageSender
from core.agent import amaya
from utils.storage import get_pending_reminders_summary
from utils.logging_setup import request_context

logger = logging.getLogger("Amaya.Telegram")

# Telegram 消息长度限制
MAX_MESSAGE_LENGTH = 4096
ALLOWED_AUDIO_MIME = {"audio/ogg", "audio/webm", "audio/wav", "audio/flac", "audio/mp3", "audio/mpeg"}
# 多消息缓冲窗口（秒，可在 config 中调节）
RAPID_MESSAGE_BUFFER_SECONDS = config.RAPID_MESSAGE_BUFFER_SECONDS


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


async def _typing_spinner(context: ContextTypes.DEFAULT_TYPE, chat_id: int, stop_event: asyncio.Event, interval: float = 3.0):
    """
    循环发送 typing 状态，直至 stop_event 触发。
    Telegram 的 typing 状态持续约 5 秒，所以我们每 3 秒刷新一次。
    """
    try:
        # 立即发送第一次 typing（不等待）
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except (TelegramError, NetworkError) as e:
            logger.debug(f"首次 typing 发送失败: {e}")

        while not stop_event.is_set():
            try:
                # 等待 stop_event 或超时
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                break  # stop_event 被设置，退出循环
            except asyncio.TimeoutError:
                # 超时，发送下一次 typing
                try:
                    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                except (TelegramError, NetworkError) as e:
                    logger.debug(f"typing 发送失败: {e}")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.debug(f"typing spinner 异常: {e}")


def _format_batch_response(pairs: List[Tuple[str, str]]) -> str:
    """
    将多条用户输入与模型回复合并为单条输出。

    示例：
        输入: [("Hi", "你好"), ("再见", "好的，再见")]
        输出:
        收到连续多条消息，合并回复如下：
        1. 用户输入：Hi
        回复：你好

        2. 用户输入：再见
        回复：好的，再见
    """
    if not pairs:
        return "抱歉，没有可用的回复。"
    if len(pairs) == 1:
        return pairs[0][1]

    blocks = ["收到连续多条消息，合并回复如下："]
    for idx, (user_text, resp) in enumerate(pairs, 1):
        sanitized = user_text.strip() if user_text else "(空消息)"
        blocks.append(f"{idx}. 用户输入：{sanitized}\n回复：{resp}")
    return "\n\n".join(blocks)


class ChatSessionBuffer:
    """
    为同一 chat_id 缓冲短时间内的多条消息，串行处理后合并回复。
    结构保持简单：仅用一个队列 + 一个后台 task，无额外线程或锁。
    """

    def __init__(self, chat_id: int, buffer_seconds: float = RAPID_MESSAGE_BUFFER_SECONDS):
        self.chat_id = chat_id
        self.buffer_seconds = buffer_seconds
        self.queue: List[Tuple[str, object, str]] = []
        self.processing = False
        self.new_message_event = asyncio.Event()

    def enqueue(self, user_text: str, message_obj, request_id: str) -> None:
        self.queue.append((user_text, message_obj, request_id))
        self.new_message_event.set()

    async def process(self, context: ContextTypes.DEFAULT_TYPE):
        """
        处理累积的消息：
        1) 初始等待 buffer_seconds 收集短间隔连发的文本；
        2) 将当前队列串行调用 Agent 并合并回复；
        3) 若在处理期间有新消息到达，再次循环，直到队列空且无新输入。
        """
        if self.processing:
            return
        self.processing = True

        stop_event = asyncio.Event()
        spinner = asyncio.create_task(_typing_spinner(context, self.chat_id, stop_event))

        try:
            # 初始小缓冲，收集同一瞬间的消息
            await asyncio.sleep(self.buffer_seconds)

            while True:
                if not self.queue:
                    try:
                        await asyncio.wait_for(self.new_message_event.wait(), timeout=self.buffer_seconds)
                        self.new_message_event.clear()
                    except asyncio.TimeoutError:
                        break

                # 拷贝队列并清空，避免重复处理
                batch = list(self.queue)
                self.queue.clear()
                self.new_message_event.clear()

                responses: List[Tuple[str, str]] = []
                for user_text, message_obj, request_id in batch:
                    with request_context(request_id):
                        try:
                            logger.info(
                                "处理文本消息 chat_id=%s len=%s",
                                self.chat_id,
                                len(user_text or ""),
                            )
                            resp = await asyncio.to_thread(
                                amaya.chat_sync, user_text, request_id=request_id
                            )
                        except Exception as e:
                            logger.error(f"聊天处理异常: {e}")
                            resp = "抱歉，处理消息时发生错误，请稍后重试。"
                    responses.append((user_text, resp))

                combined = _format_batch_response(responses)
                target_message = batch[-1][1]
                await _send_with_fallback(target_message, combined)
                logger.info(
                    "批处理回复已发送 chat_id=%s messages=%s response_len=%s",
                    self.chat_id,
                    len(responses),
                    len(combined),
                )

                # 短暂停顿，观察是否有新的消息进入队列
                try:
                    await asyncio.wait_for(self.new_message_event.wait(), timeout=self.buffer_seconds)
                    self.new_message_event.clear()
                    continue
                except asyncio.TimeoutError:
                    if not self.queue:
                        break
        finally:
            stop_event.set()
            try:
                await asyncio.wait_for(spinner, timeout=1.0)
            except asyncio.TimeoutError:
                spinner.cancel()
            self.processing = False


# 维护各 chat 的缓冲实例
CHAT_BUFFERS: dict[int, ChatSessionBuffer] = {}


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

    with request_context() as request_id:
        logger.info("收到文本消息 chat_id=%s len=%s", chat_id, len(user_text or ""))
        session = CHAT_BUFFERS.setdefault(chat_id, ChatSessionBuffer(chat_id))
        session.enqueue(user_text, update.message, request_id)

    # 独立任务处理队列，允许新的消息快速返回（合并后统一回复）
    if not session.processing:
        asyncio.create_task(session.process(context))


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update.effective_chat.id):
        await update.message.reply_text("未授权。仅限 OWNER 使用。")
        return

    chat_id = update.effective_chat.id
    stop_event = asyncio.Event()
    spinner = asyncio.create_task(_typing_spinner(context, chat_id, stop_event))
    await asyncio.sleep(0)  # 让出控制权

    response_text = None
    with request_context() as request_id:
        try:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            image_bytes = await file.download_as_bytearray()
            caption = update.message.caption or "用户发来了一张图片"
            logger.info(
                "收到图片消息 chat_id=%s caption_len=%s image_bytes=%s",
                chat_id,
                len(caption or ""),
                len(image_bytes),
            )
            # 使用 to_thread 在线程池中运行阻塞的 Gemini 调用
            response_text = await asyncio.to_thread(
                amaya.chat_sync,
                caption,
                image_bytes=bytes(image_bytes),
                request_id=request_id,
            )
        except Exception as e:
            logger.error(f"图片处理失败: {e}")
            response_text = "抱歉，图片处理失败，请重试。"
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(spinner, timeout=1.0)
        except asyncio.TimeoutError:
            spinner.cancel()

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
    await asyncio.sleep(0)  # 让出控制权

    response_text = None
    with request_context() as request_id:
        try:
            file = await context.bot.get_file(voice.file_id)
            audio_bytes = await file.download_as_bytearray()
            mime_type = getattr(voice, "mime_type", None) or "audio/ogg"
            audio_bytes, mime_type = _ensure_supported_audio(bytes(audio_bytes), mime_type)
            if audio_bytes is None:
                await update.message.reply_text("当前语音格式不受支持，请以 OGG/OPUS/WEBM/WAV 重新发送。")
            else:
                logger.info(
                    "收到语音消息 chat_id=%s mime=%s audio_bytes=%s",
                    chat_id,
                    mime_type,
                    len(audio_bytes),
                )
                user_hint = "[语音消息] 用户发来了一段语音，请结合上下文提炼关键内容进行回应。"
                # 使用 to_thread 在线程池中运行阻塞的 Gemini 调用
                response_text = await asyncio.to_thread(
                    amaya.chat_sync,
                    user_hint,
                    audio_bytes=audio_bytes,
                    audio_mime=mime_type,
                    request_id=request_id,
                )
        except TelegramError as e:
            logger.error(f"语音下载失败: {e}")
            await update.message.reply_text(f"下载语音失败: {e}")
        except Exception as e:
            logger.error(f"语音处理失败: {e}")
            response_text = "抱歉，语音处理失败，请重试。"
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(spinner, timeout=1.0)
        except asyncio.TimeoutError:
            spinner.cancel()

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
