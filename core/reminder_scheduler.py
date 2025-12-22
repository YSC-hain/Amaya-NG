# core/reminder_scheduler.py
import os
import json
import logging
import time
import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from typing import TYPE_CHECKING

from core.agent import amaya
from utils.storage import load_json, save_json, build_reminder_id
import config

if TYPE_CHECKING:
    from adapters.base import MessageSender

logger = logging.getLogger("Amaya.Scheduler")


class ReminderScheduler:
    def __init__(self, scheduler: AsyncIOScheduler, sender: "MessageSender"):
        self.scheduler = scheduler
        self.sender = sender
        # 使用配置中的时区
        self.timezone = pytz.timezone(config.TIMEZONE)

    async def restore_reminders(self):
        """启动时恢复未完成的提醒"""
        reminders = load_json("pending_reminders", default=[])

        if not reminders:
            logger.info("没有需要恢复的提醒。")
            return

        logger.info(f"正在恢复 {len(reminders)} 个未执行的提醒...")
        restored_count = 0

        for reminder in reminders:
            run_at = reminder.get('run_at', 0)
            reminder_id = reminder.get('id')
            prompt = reminder.get('prompt')

            if not reminder_id:
                continue

            # 使用 datetime 进行比较更加直观
            run_date = datetime.datetime.fromtimestamp(run_at, tz=self.timezone)
            now_date = datetime.datetime.now(self.timezone)

            if run_date > now_date:
                self.scheduler.add_job(
                    self.execute_reminder,
                    trigger=DateTrigger(run_date=run_date),
                    id=reminder_id,
                    # 【关键】必须把 ID 传回去，否则回调函数不知道该删哪个
                    args=[prompt, reminder_id],
                    replace_existing=True
                )
                restored_count += 1
                logger.info(f"已恢复提醒: '{prompt}' (at {run_date})")
            else:
                # 已错过的任务，立即触发
                # 使用 apscheduler 的 run_date=now 立刻执行，而不是直接 await，保持异步一致性
                self.scheduler.add_job(
                    self.execute_reminder,
                    trigger=DateTrigger(run_date=datetime.datetime.now(self.timezone) + datetime.timedelta(seconds=1)),
                    args=[f"[延迟的提醒] {prompt}", reminder_id]
                )
                logger.warning(f"发现已错过的提醒，已安排立即补发: '{prompt}'")

        # 清理掉那些无效的数据（可选，这里暂不清理，交给 execute_reminder 逐步清理）

    async def check_system_events(self):
        """每5秒检查sys_event_bus.jsonl，注册新任务"""
        sys_bus_path = "data/sys_event_bus.jsonl"
        if not os.path.exists(sys_bus_path):
            return

        events_to_process = []
        lines_to_keep = []  # 解析失败的行，需要保留
        try:
            # 读写模式打开，读取后清空
            with open(sys_bus_path, 'r+', encoding='utf-8') as f:
                lines = f.readlines()
                if not lines:
                    return
                f.seek(0)
                f.truncate()

            for line in lines:
                if line.strip():
                    try:
                        events_to_process.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        logger.warning(f"事件解析失败，保留原数据: {e}")
                        lines_to_keep.append(line)

            # 将解析失败的行写回文件
            if lines_to_keep:
                with open(sys_bus_path, 'a', encoding='utf-8') as f:
                    f.writelines(lines_to_keep)

        except IOError as e:
            logger.error(f"总线文件读写失败: {e}")
            return
        except Exception as e:
            logger.exception(f"总线处理异常: {e}")
            return

        for event in events_to_process:
            if event.get("type") == "reminder":
                run_at = event.get("run_at")
                prompt = event.get("prompt")
                if run_at is None or prompt is None:
                    logger.warning("reminder 事件缺少 run_at 或 prompt，已跳过")
                    continue
                # 使用事件内的 ID，若缺失则生成一个
                job_id = event.get("id") or build_reminder_id(run_at)

                if run_at > time.time():
                    run_date = datetime.datetime.fromtimestamp(run_at, tz=self.timezone)

                    self.scheduler.add_job(
                        self.execute_reminder,
                        trigger=DateTrigger(run_date=run_date),
                        id=job_id,
                        args=[prompt, job_id], # 传递 ID
                        replace_existing=True
                    )
                    # 持久化
                    self.update_pending_reminders(job_id, run_at, prompt)
                    logger.info(f"新任务已调度: '{prompt}' (at {run_date})")
                else:
                    logger.warning("尝试设置过去的时间，忽略。")

            elif event.get("type") == "clear_reminder":
                # 支持删除提醒
                reminder_id = event.get("reminder_id")
                if not reminder_id:
                    logger.warning("clear_reminder 事件缺少 reminder_id")
                    continue
                try:
                    if self.scheduler.get_job(reminder_id):
                        self.scheduler.remove_job(reminder_id)
                    self.update_pending_reminders(reminder_id, 0, "", remove=True)
                    logger.info(f"已清除提醒任务: {reminder_id}")
                except Exception as e:
                    logger.error(f"清除提醒任务 {reminder_id} 失败: {e}")

    def update_pending_reminders(self, reminder_id, run_at, prompt, remove=False):
        """维护pending_reminders.json"""
        reminders = load_json("pending_reminders", default=[])
        if remove:
            reminders = [j for j in reminders if j.get("id") != reminder_id]
        else:
            # 先删除旧的同ID记录（防止重复），再添加新的   ToDo: 激进的删除策略可能造成影响
            reminders = [j for j in reminders if j.get("id") != reminder_id]
            reminders.append({"id": reminder_id, "run_at": run_at, "prompt": prompt})
        save_json("pending_reminders", reminders)

    async def execute_reminder(self, prompt, job_id):
        """[回调] 当闹钟时间到时，此函数被触发"""
        logger.info(f"触发提醒任务: {prompt}")

        # 生成提醒消息
        system_trigger = f"[SYSTEM_EVENT] 提醒时间已到。原定计划是：'{prompt}'。请根据此指令，并结合当前记忆，生成一条提醒信息。"
        response = await amaya.chat(system_trigger)

        # 通过抽象接口发送消息
        await self.sender.send_text(response)

        self.update_pending_reminders(job_id, 0, "", remove=True)
        logger.info(f"任务 {job_id} 已完成并从持久化记录中移除。")
