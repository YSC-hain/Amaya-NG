# main.py
import os
import json
import logging
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

import config
from core.agent import amaya
from core.tools import SYS_EVENT_FILE
from utils.storage import load_json, save_json, get_pending_jobs_summary


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
    summary = get_pending_jobs_summary()
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
        summary = get_pending_jobs_summary()
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
async def maintenance_job(context: ContextTypes.DEFAULT_TYPE):
    """后台任务：触发 Amaya 自主整理"""
    if config.OWNER_ID:
        # 通知用户开始整理（可选，也可以静默进行）
        # await context.bot.send_message(chat_id=config.OWNER_ID, text="🌙 Amaya 正在整理记忆碎片...")

        # 调用大脑的整理功能
        report = await amaya.tidying_up()

        # 整理完发个报告（或者存日志）
        # await context.bot.send_message(chat_id=config.OWNER_ID, text=f"✨ 整理完成。\n{report}")
        logger.info(f"Maintenance Report: {report}")



# --- 动态提醒与持久化逻辑 ---

def update_pending_jobs(job_id, run_at, prompt, remove=False):
    """维护 data/pending_jobs.json 文件，确保任务持久化"""
    jobs = load_json("pending_jobs", default=[])
    if remove:
        jobs = [j for j in jobs if j.get("id") != job_id]
    else:
        jobs.append({"id": job_id, "run_at": run_at, "prompt": prompt})
    save_json("pending_jobs", jobs)

async def execute_reminder(context: ContextTypes.DEFAULT_TYPE):
    """[回调] 当闹钟时间到时，此函数被触发"""
    job = context.job
    prompt = job.data
    job_id = job.name

    logger.info(f"触发提醒任务: {prompt}")

    # 1. 构造系统指令，让 Amaya 组织语言
    system_trigger = f"[SYSTEM_EVENT] 提醒时间已到。原定计划是：'{prompt}'。请根据此指令，并结合当前记忆，生成一条提醒信息。"
    response = await amaya.chat(system_trigger)

    # 2. 发送提醒
    if config.OWNER_ID:
        await context.bot.send_message(
            chat_id=config.OWNER_ID,
            text=response,
            parse_mode='Markdown'
        )

    # 3. 【关键】从持久化文件中移除已完成的任务
    update_pending_jobs(job_id, 0, "", remove=True)
    logger.info(f"任务 {job_id} 已完成并从持久化记录中移除。")


# 系统总线监听器 (这是负责从文件里拿任务的人)
async def check_system_events(context: ContextTypes.DEFAULT_TYPE):
    """[后台任务] 每5秒检查一次 sys_event_bus.jsonl，注册新任务"""
    sys_bus_path = "data/sys_event_bus.jsonl"
    if not os.path.exists(sys_bus_path):
        return

    try:
        with open(sys_bus_path, 'r+', encoding='utf-8') as f:
            lines = f.readlines()
            if not lines:
                return

            # 清空文件，防止重复处理
            f.seek(0)
            f.truncate()

        for line in lines:
            if not line.strip(): continue
            event = json.loads(line)

            if event.get("type") == "reminder":
                run_at = event["run_at"]
                delay = run_at - time.time()
                prompt = event["prompt"]
                job_id = f"reminder_{int(run_at)}"

                if delay > 0:
                    # 注册到内存 JobQueue
                    context.job_queue.run_once(execute_reminder, delay, name=job_id, data=prompt)
                    # 写入持久化文件
                    update_pending_jobs(job_id, run_at, prompt)
                    logger.info(f"已调度并持久化新任务: '{prompt}' ({int(delay)}s后)")
            elif event.get("type") == "clear_reminder":
                reminder_id = event["reminder_id"]
                jobs = context.job_queue.get_jobs_by_name(reminder_id)
                if jobs:
                    jobs[0].schedule_removal()
                update_pending_jobs(reminder_id, 0, "", remove=True)
                logger.info(f"已清除提醒任务: {reminder_id}")
    except Exception as e:
        logger.error(f"处理系统事件总线失败: {e}")

async def restore_jobs(context: ContextTypes.DEFAULT_TYPE):
    """[启动任务] 程序启动时，恢复所有未完成的持久化任务"""
    jobs = load_json("pending_jobs", default=[])
    now = time.time()
    if not jobs:
        logger.info("没有需要恢复的任务。")
        return

    logger.info(f"正在恢复 {len(jobs)} 个未完成的任务...")
    for job in jobs:
        delay = job.get('run_at', 0) - now
        job_id = job.get('id')
        prompt = job.get('prompt')

        if not job_id: continue

        if delay > 0:
            context.job_queue.run_once(execute_reminder, delay, name=job_id, data=prompt)
            logger.info(f"已恢复任务: '{prompt}' ({int(delay)}s后)")
        else:
            # 对于已错过的任务，立即触发
            context.job_queue.run_once(execute_reminder, 1, name=job_id, data=f"[延迟的提醒] {prompt}")
            logger.warning(f"发现已错过的任务，将立即补发: '{prompt}'")


# --- 5. 主程序入口 ---
if __name__ == '__main__':
    # 构建 App
    application = ApplicationBuilder().token(config.TOKEN).build()

    # 注册命令 (Command Handlers)
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('ping', ping))
    application.add_handler(CommandHandler('reminders', reminders))

    # 注册回调查询处理器
    application.add_handler(CallbackQueryHandler(handle_callback))

    # 注册消息处理器 (Message Handler) - 必须放在命令之后
    # 过滤掉命令，只处理纯文本
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    # 注册后台定时任务 (JobQueue)
    job_queue = application.job_queue
    if config.OWNER_ID:
        job_queue.run_once(restore_jobs, 1, name="restore_jobs_on_startup")  # 【关键】启动1秒后，执行一次恢复任务

        job_queue.run_repeating(check_system_events, interval=5, first=5, name="system_bus_check")
        job_queue.run_repeating(maintenance_job, interval=28800, first=7200)

    logger.info("Agent 正在启动...")
    # 跑起来！
    application.run_polling()
