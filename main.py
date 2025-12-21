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
    format='%(asctime)s - %(levelname)s - %(message)s', # 简化格式，去掉 name
    level=logging.INFO
)

# 屏蔽第三方库的烦人信息
logging.getLogger("apscheduler").setLevel(logging.WARNING) # 只显示警告和错误
logging.getLogger("httpx").setLevel(logging.WARNING)       # 屏蔽网络请求详情
logging.getLogger("google.genai").setLevel(logging.WARNING) # 屏蔽 Gemini 内部心跳
logging.getLogger("telegram.ext._application").setLevel(logging.WARNING) # 屏蔽 TG 轮询信息

logger = logging.getLogger("Amaya")


# --- 定义处理函数 (Handlers) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    当用户发送 /start 时触发。
    同时这也是获取你 User ID 的好机会。
    """
    user = update.effective_user
    chat_id = update.effective_chat.id

    # 在控制台打印 ID，你可以把它复制到 .env 文件里
    logger.info(f"User {user.first_name} started the bot. Chat ID: {chat_id}")

    await update.message.reply_text(
        f"你好，{user.first_name}。\n"
        f"我是 Amaya 原型机。\n"
        f"你的 ID 是: `{chat_id}` (已记录)\n\n"
        "功能测试：\n"
        "1. 发送 /ping 测试延迟\n"
        "2. 发送 /reminders 查看挂起的提醒任务",
        parse_mode='Markdown'
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """测试基本响应"""
    await update.message.reply_text("Pong! 系统在线。")  # ToDo: 可以在这放置一些系统的基础信息

async def reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看挂起的提醒任务"""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    summary = get_pending_reminders_summary()
    keyboard = [
        [InlineKeyboardButton("刷新", callback_data='refresh_reminders')],
        [InlineKeyboardButton("关闭", callback_data='close_reminders')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(summary, reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调"""
    query = update.callback_query
    await query.answer()

    if query.data == 'refresh_reminders':
        summary = get_pending_reminders_summary()
        keyboard = [
            [InlineKeyboardButton("刷新", callback_data='refresh_reminders')],
            [InlineKeyboardButton("关闭", callback_data='close_reminders')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=summary, reply_markup=reply_markup)
    elif query.data == 'close_reminders':
        await query.delete_message()

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    将消息转发给 Amaya 的大脑
    """
    user_text = update.message.text
    logger.info(f"收到用户消息: {user_text}")
    chat_id = update.effective_chat.id

    # 简单的鉴权：只服务 Owner (防止被别人蹭用)
    # 如果 config.OWNER_ID 没填，所有人都能用
    if config.OWNER_ID and str(chat_id) != config.OWNER_ID:
        await update.message.reply_text("Amaya 是私人助理，未授权访问。")
        return

    # 发送 "输入中..." 的状态 (让体验更真实)
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # 1. 调用大脑
    response_text = await amaya.chat(user_text)

    # 再次发送typing以确保持续
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    logger.info(f"Amaya 回复: {response_text[:50]}...")

    try:
        # 尝试用 Markdown 发送
        await update.message.reply_text(response_text, parse_mode='Markdown')
    except Exception as e:
        # 如果报错，说明 AI 生成了非法 Markdown 字符
        # 此时作为纯文本发送，保证用户能看到回复
        logger.warning(f"Markdown 解析失败，回退至纯文本: {e}")
        await update.message.reply_text(response_text)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理图片消息"""
    photo = update.message.photo[-1] # 获取最高清的版本
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()

    caption = update.message.caption or "用户发来了一张图片"
    logger.info(f"收到用户图片, 说明: {caption}")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response_text = await amaya.chat(caption, image_bytes=bytes(image_bytes))

    # 再次发送typing以确保持续
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        await update.message.reply_text(response_text, parse_mode='Markdown')
    except Exception as e:
        logger.warning(f"Markdown 解析失败(图片)，回退至纯文本: {e}")
        await update.message.reply_text(response_text)


# --- 定义整理任务 ---
async def maintenance_job():
    """后台任务：触发 Amaya 自主整理"""
    if config.OWNER_ID:
        # 调用大脑的整理功能
        report = await amaya.tidying_up()
        logger.info(f"Maintenance Report: {report}")



# --- 5. 主程序入口 ---
if __name__ == '__main__':
    # 1. 初始化调度器 (但不立即启动)
    scheduler = AsyncIOScheduler()

    # 2. 定义启动钩子函数
    async def on_startup(app):
        """在 Bot 启动且事件循环就绪后执行"""
        # 初始化自定义调度器逻辑
        # 注意：这里我们传入 app.bot，确保调度器能发消息
        reminder_scheduler = ReminderScheduler(scheduler, app.bot)

        # 启动调度器 (此时 loop 已存在，不会报错)
        scheduler.start()

        if config.OWNER_ID:
            # 添加任务
            # 使用 datetime.datetime.now() 更符合直觉
            now = datetime.datetime.now()

            # 立即恢复提醒 (延迟1秒)
            scheduler.add_job(
                reminder_scheduler.restore_reminders,
                'date',
                run_date=now + datetime.timedelta(seconds=1)
            )

            # 系统事件检查 (每5秒)
            scheduler.add_job(
                reminder_scheduler.check_system_events,
                'interval',
                seconds=5
            )

            # 维护任务 (每8小时)
            scheduler.add_job(
                maintenance_job,
                'interval',
                hours=8
            )

        logger.info("[Init] 调度器已在 post_init 中成功启动")



    # 3. 构建 App (注入 post_init)
    application = (
        ApplicationBuilder()
        .token(config.TOKEN)
        .post_init(on_startup) # <--- 关键修改：注册启动钩子
        .build()
    )

    # 4. 注册 Handlers (保持不变)
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('ping', ping))
    application.add_handler(CommandHandler('reminders', reminders))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    logger.info("Agent 正在启动...")
    # 跑起来！
    application.run_polling(stop_signals=None)
