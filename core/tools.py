# core/tools.py
import time
import logging
import datetime
import pytz
import requests
from typing import List, Optional
import config
from utils.storage import (
    list_files_in_memory,
    read_file_content,
    write_file_content,
    delete_file,
    toggle_pin_status,
    build_reminder_id,
    append_event_to_bus
)
from utils.user_context import get_current_user_id

logger = logging.getLogger("Amaya.Tools")

def list_memories() -> str:
    """
    查看记忆库里有哪些文件
    """
    try:
        files = list_files_in_memory()
        return f"Files: {', '.join(files)}" if files else "Memory is empty."
    except Exception as e:
        return f"列出文件失败: {str(e)}"

# --- 2. 操作类工具 ---

def read_memory(filename: str) -> str:
    """
    读取某个文件的详细内容

    Args:
        filename: 具体的记忆文件名
    """
    if not filename:
        return "错误：缺少文件名参数。"
    content = read_file_content(filename)
    if content is None:
        return f"File '{filename}' not found."
    return content if content else "文件内容为空。"

def save_memory(filename: str, content: str) -> str:
    """
    保存记忆。
    - 如果是记日记，可以叫 journal_2025.txt
    - 如果是任务，可以叫 current_tasks.md
    - 该函数不能用来修改reminder

    Args:
        filename: 具体的记忆文件名
        content: 要保存的内容, 注意这会覆盖原本的内容
    """
    if not filename:
        return "错误：缺少文件名参数。"
    if content is None:
        content = ""
    if write_file_content(filename, content):
        return f"Saved to {filename}."
    return f"Save to {filename} failed."

def archive_memory(filename: str) -> str:
    """
    删除或归档不再需要的文件

    Args:
        filename: 具体的记忆文件名
    """
    if not filename:
        return "错误：缺少文件名参数。"
    if delete_file(filename):
        return f"Deleted {filename}."
    return f"Delete {filename} failed. File may not exist."

def pin_memory(filename: str, is_pinned: bool = True) -> str:
    """
    将文件标记为'置顶记忆'或是取消标记
    被 Pin 的文件内容会在每次对话时自动出现在你的脑海里。
    用于存储：用户性格、核心长期目标、当前正在进行的复杂项目、最近的安排。

    Args:
        filename: 具体的记忆文件名
        is_pinned: True 表示 Pin, False 表示 Unpin
    """
    if not filename:
        return "错误：缺少文件名参数。"
    try:
        status = toggle_pin_status(filename, is_pinned)
        action = "Pinned" if status else "Unpinned"
        return f"File {filename} is now {action}."
    except Exception as e:
        return f"Pin/Unpin {filename} failed: {str(e)}"


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
    if not prompt or not prompt.strip():
        return "错误：缺少 prompt 参数，请提供提醒内容。"

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
    user_id = get_current_user_id()
    event = {
        "type": "reminder",
        "id": reminder_id,
        "user_id": user_id,
        "created_at": now,
        "run_at": run_at,
        "prompt": prompt
    }

    if append_event_to_bus(event):
        human_time = datetime.datetime.fromtimestamp(run_at, tz=tz).strftime("%m-%d %H:%M:%S")
        logger.debug(f"已创建提醒 {reminder_id}: {prompt} @ {human_time}")
        return f"指令已下达（ID: {reminder_id}）：计划 {delay_seconds} 秒后 / {human_time} 执行 '{prompt}'。"
    return "设置失败: 写入事件总线异常。"


def clear_reminder(reminder_id: str) -> str:
    """
    清除某个reminder

    Args:
        reminder_id: 具体的id, 例如"reminder_1766242804"
    """
    if not reminder_id:
        return "错误：缺少 reminder_id 参数。"

    user_id = get_current_user_id()
    event = {
        "type": "clear_reminder",
        "reminder_id": reminder_id,
        "user_id": user_id
    }

    if append_event_to_bus(event):
        logger.debug(f"已请求清除提醒: {reminder_id}")
        return f"指令已下达：清除定时提醒, ID: {reminder_id}"
    return "设置失败: 写入事件总线异常。"


# --- 3. 信息获取类工具 ---
# ToDo: 优化
def get_weather(city: str) -> str:
    """
    获取指定城市的天气。

    Args:
        city: 城市名称，如 "Beijing", "Shanghai", "Shenzhen"。
    """
    city = (city or "").strip()
    if not city:
        return "请提供城市名称，例如 Shanghai。"
    try:
        url = f"https://wttr.in/{requests.utils.quote(city)}?format=3&lang=zh"
        response = requests.get(url, timeout=config.WEATHER_TIMEOUT_SECONDS, headers={"User-Agent": "Amaya/1.0"})
        if response.status_code == 200:
            return f"{city} 天气: {response.text.strip()}"
        return f"无法获取 {city} 的天气信息，HTTP {response.status_code}。"
    except requests.RequestException as e:
        return f"获取天气失败（网络问题）: {str(e)}"
    except Exception as e:
        return f"获取天气失败: {str(e)}"


def get_china_holiday(date_str: Optional[str] = None) -> str:
    """
    查询中国节假日信息。

    Args:
        date_str: 日期字符串 "YYYY-MM-DD"。如果不传则默认查询今天。
    """
    if not date_str:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    try:
        url = f"https://timor.tech/api/holiday/info/{date_str}"
        headers = {"User-Agent": "Amaya/1.0"}
        response = requests.get(url, headers=headers, timeout=config.HOLIDAY_TIMEOUT_SECONDS)
        data = response.json()

        if data.get("code") != 0:
            return f"查询失败: {data.get('message')}"

        info = data.get("type", {})
        type_map = {0: "工作日", 1: "周末", 2: "法定节假日", 3: "调休(需要上班)"}

        type_val = info.get("type")
        type_name = type_map.get(type_val, "未知")
        name = info.get("name", "")

        result = f"{date_str} 是 {type_name}"
        if name:
            result += f" ({name})"

        return result
    except requests.RequestException as e:
        return f"获取节假日信息失败（网络问题）: {str(e)}"
    except Exception as e:
        return f"获取节假日信息失败: {str(e)}"


# 注册所有工具
tools_registry: List = [
    list_memories,
    read_memory,
    save_memory,
    archive_memory,
    pin_memory,
    schedule_reminder,
    clear_reminder,
    get_weather,
    get_china_holiday
]
