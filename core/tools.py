# core/tools.py
import json
import time
import logging
import datetime
import pytz
from typing import List, Optional
import config
from utils.storage import (
    list_files_in_memory,
    read_file_content,
    write_file_content,
    delete_file,
    toggle_pin_status,
    build_reminder_id
)

logger = logging.getLogger("Amaya.Tools")


# --- 1. 感知类工具 ---

def list_memories() -> str:
    """
    查看记忆库里有哪些文件
    """
    files = list_files_in_memory()
    return f"Files: {', '.join(files)}" if files else "Memory is empty."

# --- 2. 操作类工具 ---

def read_memory(filename: str) -> str:
    """
    读取某个文件的详细内容
    """
    content = read_file_content(filename)
    if content is None:
        return "File not found."
    return content

def save_memory(filename: str, content: str) -> str:
    """
    保存记忆。
    - 如果是记日记，可以叫 journal_2025.txt
    - 如果是任务，可以叫 current_tasks.md
    - 该函数不能用来修改reminder
    """
    if write_file_content(filename, content):
        return f"Saved to {filename}."
    return "Save failed."

def archive_memory(filename: str) -> str:
    """
    删除或归档不再需要的文件
    """
    if delete_file(filename):
        return f"Deleted {filename}."
    return "Delete failed."

def pin_memory(filename: str, is_pinned: bool = True) -> str:
    """
    将文件标记为'置顶记忆'或是取消标记
    被 Pin 的文件内容会在每次对话时自动出现在你的脑海里。
    用于存储：用户性格、核心长期目标、当前正在进行的复杂项目、最近的安排。
    """
    status = toggle_pin_status(filename, is_pinned)
    action = "Pinned" if status else "Unpinned"
    return f"File {filename} is now {action}."


SYS_EVENT_FILE = "data/sys_event_bus.jsonl"  # 保持不变


def _parse_target_time(target_time: str, tz: pytz.BaseTzInfo) -> Optional[float]:
    try:
        dt = datetime.datetime.fromisoformat(target_time)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = tz.localize(dt)
    else:
        dt = dt.astimezone(tz)
    return dt.timestamp()


def schedule_reminder(delay_seconds: Optional[int] = None, prompt: str = "", target_time: Optional[str] = None) -> str:
    """
    设置一个 reminder。

    Args:
        delay_seconds: 延迟多少秒后触发；与 target_time 互斥，target_time 优先。
        prompt: 提醒时要执行的指令。
        target_time: 绝对时间（ISO 8601，如 "2025-12-23T08:00:00"，可省略 "T"）。
    """
    if not prompt:
        return "缺少 prompt。"

    tz = pytz.timezone(config.TIMEZONE)
    now = time.time()
    run_at = None

    if target_time:
        run_at = _parse_target_time(target_time, tz)
        if run_at is None:
            return "target_time 解析失败，请使用 ISO 格式，如 2025-12-23T08:00:00。"
        delay_seconds = max(0, int(run_at - now))
    elif delay_seconds is not None:
        delay_seconds = max(0, int(delay_seconds))
        run_at = now + delay_seconds
    else:
        return "请提供 delay_seconds 或 target_time。"

    reminder_id = build_reminder_id(run_at)
    event = {
        "type": "reminder",
        "id": reminder_id,
        "created_at": now,
        "run_at": run_at,
        "prompt": prompt
    }

    try:
        with open(SYS_EVENT_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        human_time = datetime.datetime.fromtimestamp(run_at, tz=tz).strftime("%m-%d %H:%M:%S")
        logger.debug(f"已创建提醒 {reminder_id}: {prompt} @ {human_time}")
        return f"指令已下达（ID: {reminder_id}）：计划 {delay_seconds} 秒后 / {human_time} 执行 '{prompt}'。"
    except IOError as e:
        logger.error(f"写入事件总线失败: {e}")
        return f"设置失败: {str(e)}"


def clear_reminder(reminder_id: str) -> str:
    """
    清除某个reminder

    Args:
        reminder_id: 具体的id, 例如"reminder_1766242804"
    """
    event = {
        "type": "clear_reminder",
        "reminder_id": reminder_id
    }

    try:
        with open(SYS_EVENT_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        logger.debug(f"已请求清除提醒: {reminder_id}")
        return f"指令已下达：清除定时提醒, ID: {reminder_id}"
    except IOError as e:
        logger.error(f"写入事件总线失败: {e}")
        return f"设置失败: {str(e)}"


# 注册所有工具
tools_registry: List = [
    list_memories,
    read_memory,
    save_memory,
    archive_memory,
    pin_memory,
    schedule_reminder,
    clear_reminder
]
