# main.py
import logging
import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from core.agent import amaya
from core.reminder_scheduler import ReminderScheduler
from utils.storage import get_pending_reminders_summary

# --- 设置日志 ---
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google.genai").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._application").setLevel(logging.WARNING)

logger = logging.getLogger("Amaya")

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(f"User {user.first_name} started the bot. Chat ID: {chat_id}")
    await update.message.reply_text(
        f"你好，{user.first_name}。\n我是 Amaya 原型机。\nID: `{chat_id}`",
        parse_mode='Markdown'
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pong! 系统在线。")

async def reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看挂起的提醒任务"""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    summary = get_pending_reminders_summary() # 确保 utils/storage.py 里有这个函数
    keyboard = [
        [InlineKeyboardButton("刷新", callback_data='refresh_reminders')],
        [InlineKeyboardButton("关闭", callback_data='close_reminders')]
    ]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'refresh_reminders':
        summary = get_pending_reminders_summary()
        keyboard = [
            [InlineKeyboardButton("刷新", callback_data='refresh_reminders')],
            [InlineKeyboardButton("关闭", callback_data='close_reminders')]
        ]
        try:
            await query.edit_message_text(text=summary, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as _:
            pass # 内容未变时不报错
    elif query.data == 'close_reminders':
        await query.delete_message()

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id = update.effective_chat.id

    if config.OWNER_ID and str(chat_id) != config.OWNER_ID:
        await update.message.reply_text("未授权。")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    response_text = await amaya.chat(user_text)
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    logger.info(f"Amaya 回复: {response_text[:50]}...")

    try:
        await update.message.reply_text(response_text, parse_mode='Markdown')
    except Exception as e:
        logger.warning(f"Markdown 发送失败: {e}")
        await update.message.reply_text(response_text)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()
    caption = update.message.caption or "用户发来了一张图片"

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response_text = await amaya.chat(caption, image_bytes=bytes(image_bytes))

    try:
        await update.message.reply_text(response_text, parse_mode='Markdown')
    except Exception as _:
        await update.message.reply_text(response_text)

# --- 维护任务 ---
async def maintenance_job():
    """后台任务：触发 Amaya 自主整理"""
    if config.OWNER_ID:
        report = await amaya.tidying_up()
        logger.info(f"Maintenance Report: {report}")

# --- 主程序入口 ---
if __name__ == '__main__':
    # 1. 初始化调度器
    scheduler = AsyncIOScheduler()

    # 2. 启动钩子
    async def on_startup(app):
        # 初始化自定义调度逻辑
        reminder_scheduler = ReminderScheduler(scheduler, app.bot)

        # 启动调度器
        scheduler.start()
        logger.info("✅ 调度器已启动")

        if config.OWNER_ID:
            now = datetime.datetime.now()

            # 立即恢复任务
            scheduler.add_job(reminder_scheduler.restore_reminders, 'date', run_date=now + datetime.timedelta(seconds=1))

            # 监听系统总线 (每5秒)
            scheduler.add_job(reminder_scheduler.check_system_events, 'interval', seconds=5)

            # 每日整理 (每8小时)
            scheduler.add_job(maintenance_job, 'interval', hours=8)

    # 3. 构建 App
    application = (
        ApplicationBuilder()
        .token(config.TOKEN)
        .post_init(on_startup)
        .build()
    )

    # 4. 注册 Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('ping', ping))
    application.add_handler(CommandHandler('reminders', reminders))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    logger.info("Agent 正在启动...")
    application.run_polling(stop_signals=None)