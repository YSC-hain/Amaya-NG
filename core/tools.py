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
    append_event_to_bus,
    load_schedule,
    save_schedule,
    build_schedule_item_id,
    get_schedule_summary
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


# --- 3. 结构化日程表工具 ---
def _parse_schedule_date(date_str: str) -> Optional[datetime.date]:
    try:
        return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _parse_schedule_time(time_str: str) -> Optional[int]:
    if not time_str:
        return None
    try:
        value = datetime.datetime.strptime(time_str, "%H:%M")
    except (TypeError, ValueError):
        return None
    return value.hour * 60 + value.minute


def _normalize_tags(tags: Optional[List[str]]) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    if not isinstance(tags, list):
        return []
    return [str(t).strip() for t in tags if str(t).strip()]


def _get_schedule_day(schedule: dict, date_str: str, create: bool = False) -> Optional[dict]:
    for day in schedule.get("days", []):
        if day.get("date") == date_str:
            return day
    if create:
        day = {"date": date_str, "items": []}
        schedule.setdefault("days", []).append(day)
        return day
    return None


def _sort_schedule_items(items: list[dict]) -> list[dict]:
    def _key(item: dict) -> tuple:
        start = _parse_schedule_time(item.get("start", ""))
        return (start if start is not None else 24 * 60 + 1, item.get("title", ""))
    return sorted(items, key=_key)


def _find_schedule_conflicts(items: list[dict], start: int, end: int, ignore_id: Optional[str] = None) -> list[dict]:
    conflicts = []
    for item in items:
        if ignore_id and item.get("id") == ignore_id:
            continue
        item_start = _parse_schedule_time(item.get("start", ""))
        item_end = _parse_schedule_time(item.get("end", ""))
        if item_start is None or item_end is None:
            continue
        if max(start, item_start) < min(end, item_end):
            conflicts.append(item)
    return conflicts


def list_schedule(date: Optional[str] = None, days: int = 7) -> str:
    """
    查看结构化日程表摘要。

    Args:
        date: 起始日期 "YYYY-MM-DD"，不传则默认今天。
        days: 连续天数，默认 7 天。
    """
    try:
        return get_schedule_summary(start_date=date, days=days)
    except Exception as e:
        return f"读取日程表失败: {str(e)}"


def add_schedule_item(
    date: str,
    start_time: str,
    end_time: str,
    title: str,
    location: str = "",
    note: str = "",
    tags: Optional[List[str]] = None
) -> str:
    """
    新增日程项。

    Args:
        date: 日期 "YYYY-MM-DD"
        start_time: 开始时间 "HH:MM"
        end_time: 结束时间 "HH:MM"
        title: 事项标题
    """
    if not title or not title.strip():
        return "错误：缺少 title 参数"
    if not date or not _parse_schedule_date(date):
        return "错误：date 需要 YYYY-MM-DD 格式"
    start = _parse_schedule_time(start_time)
    end = _parse_schedule_time(end_time)
    if start is None or end is None:
        return "错误：start_time/end_time 需要 HH:MM 格式"
    if start >= end:
        return "错误：start_time 必须早于 end_time"

    schedule = load_schedule()
    day = _get_schedule_day(schedule, date, create=True)
    existing_ids = {item.get("id") for item in day.get("items", []) if item.get("id")}
    item_id = build_schedule_item_id(existing_ids=existing_ids)
    item = {
        "id": item_id,
        "start": start_time,
        "end": end_time,
        "title": title.strip(),
        "location": location.strip(),
        "note": note.strip(),
        "tags": _normalize_tags(tags)
    }
    conflicts = _find_schedule_conflicts(day.get("items", []), start, end)
    day["items"].append(item)
    day["items"] = _sort_schedule_items(day["items"])

    if save_schedule(schedule):
        conflict_note = ""
        if conflicts:
            conflict_titles = ", ".join(c.get("title", "未命名") for c in conflicts)
            conflict_note = f"（注意：与 {conflict_titles} 时间冲突）"
        return f"已新增日程项 {item_id}：{date} {start_time}-{end_time} {title}{conflict_note}"
    return "新增失败：保存日程表异常"


def update_schedule_item(
    date: str,
    item_id: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    title: Optional[str] = None,
    location: Optional[str] = None,
    note: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> str:
    """
    更新日程项。

    Args:
        date: 日期 "YYYY-MM-DD"
        item_id: 事项 ID
    """
    if not date or not _parse_schedule_date(date):
        return "错误：date 需要 YYYY-MM-DD 格式"
    if not item_id:
        return "错误：缺少 item_id 参数"

    schedule = load_schedule()
    day = _get_schedule_day(schedule, date, create=False)
    if not day:
        return f"未找到 {date} 的日程"
    items = day.get("items", [])
    item = next((i for i in items if i.get("id") == item_id), None)
    if not item:
        return f"未找到日程项 {item_id}"

    new_start = start_time if start_time is not None else item.get("start", "")
    new_end = end_time if end_time is not None else item.get("end", "")
    start_val = _parse_schedule_time(new_start)
    end_val = _parse_schedule_time(new_end)
    if start_val is None or end_val is None:
        return "错误：start_time/end_time 需要 HH:MM 格式"
    if start_val >= end_val:
        return "错误：start_time 必须早于 end_time"

    if title is not None:
        item["title"] = title.strip()
    if location is not None:
        item["location"] = location.strip()
    if note is not None:
        item["note"] = note.strip()
    if tags is not None:
        item["tags"] = _normalize_tags(tags)
    item["start"] = new_start
    item["end"] = new_end

    conflicts = _find_schedule_conflicts(items, start_val, end_val, ignore_id=item_id)
    day["items"] = _sort_schedule_items(items)

    if save_schedule(schedule):
        conflict_note = ""
        if conflicts:
            conflict_titles = ", ".join(c.get("title", "未命名") for c in conflicts)
            conflict_note = f"（注意：与 {conflict_titles} 时间冲突）"
        return f"已更新日程项 {item_id}{conflict_note}"
    return "更新失败：保存日程表异常"


def move_schedule_item(
    from_date: str,
    to_date: str,
    item_id: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
) -> str:
    """
    移动日程项到其他日期，可选更新开始/结束时间。
    """
    if not from_date or not _parse_schedule_date(from_date):
        return "错误：from_date 需要 YYYY-MM-DD 格式"
    if not to_date or not _parse_schedule_date(to_date):
        return "错误：to_date 需要 YYYY-MM-DD 格式"
    if not item_id:
        return "错误：缺少 item_id 参数"

    schedule = load_schedule()
    from_day = _get_schedule_day(schedule, from_date, create=False)
    if not from_day:
        return f"未找到 {from_date} 的日程"
    items = from_day.get("items", [])
    item = next((i for i in items if i.get("id") == item_id), None)
    if not item:
        return f"未找到日程项 {item_id}"

    new_start = start_time if start_time is not None else item.get("start", "")
    new_end = end_time if end_time is not None else item.get("end", "")
    start_val = _parse_schedule_time(new_start)
    end_val = _parse_schedule_time(new_end)
    if start_val is None or end_val is None:
        return "错误：start_time/end_time 需要 HH:MM 格式"
    if start_val >= end_val:
        return "错误：start_time 必须早于 end_time"

    items.remove(item)
    if not items:
        from_day["items"] = []

    to_day = _get_schedule_day(schedule, to_date, create=True)
    item["start"] = new_start
    item["end"] = new_end
    to_day["items"].append(item)
    to_day["items"] = _sort_schedule_items(to_day["items"])

    conflicts = _find_schedule_conflicts(to_day["items"], start_val, end_val, ignore_id=item_id)
    if save_schedule(schedule):
        conflict_note = ""
        if conflicts:
            conflict_titles = ", ".join(c.get("title", "未命名") for c in conflicts)
            conflict_note = f"（注意：与 {conflict_titles} 时间冲突）"
        return f"已移动日程项 {item_id} 到 {to_date}{conflict_note}"
    return "移动失败：保存日程表异常"


def remove_schedule_item(date: str, item_id: str) -> str:
    """
    删除日程项。
    """
    if not date or not _parse_schedule_date(date):
        return "错误：date 需要 YYYY-MM-DD 格式"
    if not item_id:
        return "错误：缺少 item_id 参数"
    schedule = load_schedule()
    day = _get_schedule_day(schedule, date, create=False)
    if not day:
        return f"未找到 {date} 的日程"
    items = day.get("items", [])
    remaining = [i for i in items if i.get("id") != item_id]
    if len(remaining) == len(items):
        return f"未找到日程项 {item_id}"
    day["items"] = remaining
    if save_schedule(schedule):
        return f"已删除日程项 {item_id}"
    return "删除失败：保存日程表异常"


def clear_schedule_day(date: str) -> str:
    """
    清空某天的日程项。
    """
    if not date or not _parse_schedule_date(date):
        return "错误：date 需要 YYYY-MM-DD 格式"
    schedule = load_schedule()
    day = _get_schedule_day(schedule, date, create=False)
    if not day or not day.get("items"):
        return f"{date} 没有可清理的日程"
    count = len(day.get("items", []))
    day["items"] = []
    if save_schedule(schedule):
        return f"已清空 {date} 的 {count} 项日程"
    return "清理失败：保存日程表异常"


# --- 4. 日期/时间工具 ---
def date_diff(start_date: str, end_date: str) -> str:
    """
    计算日期差（天）。

    Args:
        start_date: "YYYY-MM-DD"
        end_date: "YYYY-MM-DD"
    """
    start = _parse_schedule_date(start_date)
    end = _parse_schedule_date(end_date)
    if not start or not end:
        return "错误：start_date/end_date 需要 YYYY-MM-DD 格式"
    diff = (end - start).days
    return f"{start_date} -> {end_date}: {diff} 天（绝对值 {abs(diff)}）"


def time_diff(start_time: str, end_time: str, allow_cross_midnight: bool = False) -> str:
    """
    计算时间差（分钟）。

    Args:
        start_time: "HH:MM"
        end_time: "HH:MM"
        allow_cross_midnight: 是否允许跨天
    """
    start = _parse_schedule_time(start_time)
    end = _parse_schedule_time(end_time)
    if start is None or end is None:
        return "错误：start_time/end_time 需要 HH:MM 格式"
    if allow_cross_midnight and end <= start:
        end += 24 * 60
    diff = end - start
    if diff < 0:
        return "错误：end_time 早于 start_time"
    return f"{start_time} -> {end_time}: {diff} 分钟"


def add_days(date_str: str, days: int) -> str:
    """
    日期加减天数。
    """
    base = _parse_schedule_date(date_str)
    if not base:
        return "错误：date 需要 YYYY-MM-DD 格式"
    try:
        delta = int(days)
    except (TypeError, ValueError):
        return "错误：days 需要整数"
    new_date = base + datetime.timedelta(days=delta)
    return f"{date_str} + {delta} 天 = {new_date.strftime('%Y-%m-%d')}"


def add_minutes(time_str: str, minutes: int) -> str:
    """
    时间加减分钟（返回时间与跨天偏移）。
    """
    base = _parse_schedule_time(time_str)
    if base is None:
        return "错误：time 需要 HH:MM 格式"
    try:
        delta = int(minutes)
    except (TypeError, ValueError):
        return "错误：minutes 需要整数"
    total = base + delta
    day_delta, minute_of_day = divmod(total, 24 * 60)
    hour = minute_of_day // 60
    minute = minute_of_day % 60
    return f"{time_str} + {delta} 分钟 = {hour:02d}:{minute:02d} (day_offset {day_delta})"


# --- 5. 信息获取类工具 ---
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
    list_schedule,
    add_schedule_item,
    update_schedule_item,
    move_schedule_item,
    remove_schedule_item,
    clear_schedule_day,
    date_diff,
    time_diff,
    add_days,
    add_minutes,
    schedule_reminder,
    clear_reminder,
    get_weather,
    get_china_holiday
]
