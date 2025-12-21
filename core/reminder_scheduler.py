import os
import json
import logging
import time
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import pytz

from core.agent import amaya
from utils.storage import load_json, save_json

logger = logging.getLogger("Amaya")

class ReminderScheduler:
    def __init__(self, scheduler: AsyncIOScheduler, bot):
        self.scheduler = scheduler
        self.bot = bot
        self.timezone = pytz.timezone('Asia/Shanghai')  # 默认时区，可配置

    async def restore_reminders(self):
        """启动时恢复未完成的提醒"""
        reminders = load_json("pending_reminders", default=[])
        now = time.time()
        if not reminders:
            logger.info("没有需要恢复的提醒。")
            return

        logger.info(f"正在恢复 {len(reminders)} 个未执行的提醒...")
        for reminder in reminders:
            run_at = reminder.get('run_at', 0)
            reminder_id = reminder.get('id')
            prompt = reminder.get('prompt')

            if not reminder_id:
                continue

            if run_at > now:
                trigger = DateTrigger(run_date=datetime.datetime.fromtimestamp(run_at, tz=self.timezone), timezone=self.timezone)
                self.scheduler.add_job(
                    self.execute_reminder,
                    trigger=trigger,
                    id=reminder_id,
                    args=[prompt]
                )
                logger.info(f"已恢复提醒: '{prompt}' (at {run_at})")
            else:
                # 已错过的任务，立即触发
                await self.execute_reminder(f"[延迟的提醒] {prompt}")
                logger.warning(f"发现已错过的提醒，将立即补发: '{prompt}'")

    async def check_system_events(self):
        """每5秒检查sys_event_bus.jsonl，注册新任务"""
        sys_bus_path = "data/sys_event_bus.jsonl"
        if not os.path.exists(sys_bus_path):
            return

        try:
            with open(sys_bus_path, 'r+', encoding='utf-8') as f:
                lines = f.readlines()
                if not lines:
                    return
                f.seek(0)
                f.truncate()

            for line in lines:
                if not line.strip():
                    continue
                event = json.loads(line)

                if event.get("type") == "reminder":
                    run_at = event["run_at"]
                    prompt = event["prompt"]
                    job_id = f"reminder_{int(run_at)}"

                    if run_at > time.time():
                        trigger = DateTrigger(run_date=datetime.datetime.fromtimestamp(run_at, tz=self.timezone), timezone=self.timezone)
                        self.scheduler.add_job(
                            self.execute_reminder,
                            trigger=trigger,
                            id=job_id,
                            args=[prompt]
                        )
                        # 持久化
                        self.update_pending_reminders(job_id, run_at, prompt)
                        logger.info(f"已调度并持久化新任务: '{prompt}' (at {run_at})")
                elif event.get("type") == "clear_reminder":
                    reminder_id = event["reminder_id"]
                    if self.scheduler.get_job(reminder_id):
                        self.scheduler.remove_job(reminder_id)
                    self.update_pending_reminders(reminder_id, 0, "", remove=True)
                    logger.info(f"已清除提醒任务: {reminder_id}")
        except Exception as e:
            logger.error(f"处理系统事件总线失败: {e}")

    def update_pending_reminders(self, reminder_id, run_at, prompt, remove=False):
        """维护pending_reminders.json"""
        reminders = load_json("pending_reminders", default=[])
        if remove:
            reminders = [j for j in reminders if j.get("id") != reminder_id]
        else:
            reminders.append({"id": reminder_id, "run_at": run_at, "prompt": prompt})
        save_json("pending_reminders", reminders)

    async def execute_reminder(self, prompt):
        """执行提醒任务"""
        logger.info(f"触发提醒任务: {prompt}")

        # 生成提醒消息
        system_trigger = f"[SYSTEM_EVENT] 提醒时间已到。原定计划是：'{prompt}'。请根据此指令，并结合当前记忆，生成一条提醒信息。"
        response = await amaya.chat(system_trigger)

        # 发送消息
        from config import OWNER_ID
        if OWNER_ID:
            try:
                await self.bot.send_message(
                    chat_id=OWNER_ID,
                    text=response,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.warning(f"发送提醒失败: {e}")
                await self.bot.send_message(chat_id=OWNER_ID, text=response)

        # 移除持久化
        job_id = f"reminder_{int(time.time())}"  # 简化ID
        self.update_pending_reminders(job_id, 0, "", remove=True)
        logger.info("任务已完成并移除。")
