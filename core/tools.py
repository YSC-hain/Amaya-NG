# core/tools.py
from datetime import datetime
import json
import time
from utils.storage import (
    list_files_in_memory,
    read_file_content,
    write_file_content,
    delete_file,
    toggle_pin_status
)


# --- 1. 感知类工具 ---

def list_memories():
    """
    查看记忆库里有哪些文件
    """
    files = list_files_in_memory()
    return f"Files: {', '.join(files)}" if files else "Memory is empty."

# --- 2. 操作类工具 ---

def read_memory(filename: str):
    """
    读取某个文件的详细内容
    """
    content = read_file_content(filename)
    if content is None:
        return "File not found."
    return content

def save_memory(filename: str, content: str):
    """
    保存记忆。
    - 如果是记日记，可以叫 journal_2025.txt
    - 如果是任务，可以叫 current_tasks.md
    - 你可以自主决定文件名和格式。
    """
    if write_file_content(filename, content):
        return f"Saved to {filename}."
    return "Save failed."

def archive_memory(filename: str):
    """
    删除或归档不再需要的文件
    """
    if delete_file(filename):
        return f"Deleted {filename}."
    return "Delete failed."

def pin_memory(filename: str, is_pinned: bool = True):
    """
    将文件标记为'置顶记忆'或是取消标记
    被 Pin 的文件内容会在每次对话时自动出现在你的脑海里。
    用于存储：用户性格、核心长期目标、当前正在进行的复杂项目、最近的安排。
    """
    status = toggle_pin_status(filename, is_pinned)
    action = "Pinned" if status else "Unpinned"
    return f"File {filename} is now {action}."


SYS_EVENT_FILE = "data/sys_event_bus.jsonl" # 保持不变

def schedule_reminder(delay_seconds: int, prompt: str):
    """
    设置一个定时提醒。

    Args:
        delay_seconds: 延迟多少秒
        prompt: 提醒时要执行的指令
    """
    event = {
        "type": "reminder",
        "created_at": time.time(),
        "run_at": time.time() + delay_seconds, # 【关键】存入绝对时间戳
        "prompt": prompt
    }

    try:
        with open(SYS_EVENT_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return f"指令已下达：{delay_seconds}秒后执行 '{prompt}'。"
    except Exception as e:
        return f"设置失败: {str(e)}"


def clear_reminder(reminder_id: str):
    """
    清除某个定时提醒

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
        return f"指令已下达：清除定时提醒, ID: {reminder_id}"
    except Exception as e:
        return f"设置失败: {str(e)}"


# 注册所有工具
tools_registry = [
    list_memories,
    read_memory,
    save_memory,
    archive_memory,
    pin_memory,
    schedule_reminder,
    clear_reminder
]