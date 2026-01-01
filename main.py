# main.py
"""
Amaya 主程序入口 —— 负责初始化调度器和启动适配器。
调度器是平台无关的核心组件，适配器可替换。
"""
import logging
import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from core.agent import amaya
from core.reminder_scheduler import ReminderScheduler
from adapters.telegram_bot import build_application, register_handlers, TelegramSender

# --- 设置日志 ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google.genai").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._application").setLevel(logging.WARNING)

logger = logging.getLogger("Amaya")


# --- 维护任务 ---
async def maintenance_job():
    """后台任务：触发 Amaya 自主整理"""
    report = await amaya.tidying_up()
    logger.info(f"Maintenance Report: {report}")


# --- 主程序入口 ---
if __name__ == "__main__":
    # 1. 初始化调度器 (平台无关)
    # 设置 misfire_grace_time 允许任务在错过时间后 60 秒内仍然执行
    # 设置 coalesce=True 合并多次错过的执行为一次
    scheduler = AsyncIOScheduler(
        job_defaults={
            'misfire_grace_time': 60,
            'coalesce': True
        }
    )

    # 2. 启动钩子
    async def on_startup(app):
        # 创建消息发送器 (Telegram 实现)
        sender = TelegramSender(app.bot)

        # 初始化提醒调度器 (注入抽象发送器，而非具体 bot)
        reminder_scheduler = ReminderScheduler(scheduler, sender)

        # 启动调度器
        scheduler.start()
        logger.info("[Init] 调度器已启动")

        now = datetime.datetime.now()

        # 立即恢复任务
        scheduler.add_job(
            reminder_scheduler.restore_reminders,
            "date",
            run_date=now + datetime.timedelta(seconds=1),
        )

        # 监听系统总线
        scheduler.add_job(
            reminder_scheduler.check_system_events,
            "interval",
            seconds=config.EVENT_BUS_CHECK_INTERVAL,
        )

        # 定期整理
        scheduler.add_job(
            maintenance_job,
            "interval",
            hours=config.MAINTENANCE_INTERVAL_HOURS,
        )

    # 3. 关闭钩子
    async def on_shutdown(app):
        logger.info("正在关闭 Amaya...")
        amaya.shutdown()
        if scheduler.running:
            scheduler.shutdown(wait=False)
        logger.info("Amaya 已安全关闭")

    # 4. 构建 App（传入钩子）
    application = build_application(post_init=on_startup, post_shutdown=on_shutdown)

    # 5. 注册 handlers
    register_handlers(application)

    logger.info("Agent 正在启动...")
    application.run_polling(stop_signals=None)