# utils/storage.py
import json
import os
import logging
import sqlite3
import threading
import re
from datetime import datetime, timedelta, date
import time
from typing import Any, Optional, List
import config
from utils.user_context import get_current_user_id

logger = logging.getLogger("Amaya.Storage")
event_logger = logging.getLogger("Amaya.EventBus")


def build_reminder_id(run_at: float) -> str:
    """基于时间戳和随机熵生成短 ID，避免同秒冲突。"""
    import secrets
    ts_part = format(int(run_at * 1000), 'x')[-8:]
    rand_part = secrets.token_hex(3)
    return f"r{ts_part}{rand_part}"


# 定义记忆库的物理路径
DATA_DIR = "data/memory_bank"
os.makedirs(DATA_DIR, exist_ok=True)
SCHEDULE_FILE = "routine.json"

# --- SQLite 存储 ---
DB_PATH = config.DB_PATH
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)
_db_lock = threading.Lock()


def _get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _db_lock, _get_db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                display_name TEXT,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_mappings (
                platform TEXT NOT NULL,
                external_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (platform, external_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_mappings_user ON user_mappings(user_id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_reminders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                run_at REAL NOT NULL,
                prompt TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS short_term_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sys_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                event_id TEXT,
                event_type TEXT,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                processed_at REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sys_events_status ON sys_events(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sys_events_type ON sys_events(event_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sys_events_user ON sys_events(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_reminders_user ON pending_reminders(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_user ON short_term_memory(user_id)")

# --- 用户映射 ---
def _create_user_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT user_id
        FROM users
        WHERE user_id GLOB '[0-9]*'
          AND user_id NOT GLOB '*[^0-9]*'
          AND length(user_id) <= 6
        ORDER BY CAST(user_id AS INTEGER) DESC
        LIMIT 1
        """
    ).fetchone()
    next_id = 1 if not row else int(row["user_id"]) + 1
    if next_id > 999999:
        raise ValueError("User id sequence exhausted (max 6 digits)")
    return f"{next_id:06d}"


def lookup_user_id(platform: str, external_id: str) -> Optional[str]:
    platform = (platform or "").strip().lower()
    external_id = str(external_id or "").strip()
    if not platform or not external_id:
        return None
    try:
        with _db_lock, _get_db_connection() as conn:
            row = conn.execute(
                "SELECT user_id FROM user_mappings WHERE platform = ? AND external_id = ?",
                (platform, external_id)
            ).fetchone()
    except sqlite3.Error as e:
        logger.error(f"User mapping lookup failed: {e}")
        return None
    return row["user_id"] if row else None


def create_user(display_name: Optional[str] = None, user_id: Optional[str] = None) -> Optional[str]:
    now = time.time()
    try:
        with _db_lock, _get_db_connection() as conn:
            resolved_user_id = user_id or _create_user_id(conn)
            row = conn.execute(
                "SELECT user_id FROM users WHERE user_id = ?",
                (resolved_user_id,)
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO users (user_id, display_name, created_at) VALUES (?, ?, ?)",
                    (resolved_user_id, display_name, now)
                )
            elif display_name:
                conn.execute(
                    "UPDATE users SET display_name = ? WHERE user_id = ?",
                    (display_name, resolved_user_id)
                )
            return resolved_user_id
    except (sqlite3.Error, ValueError) as e:
        logger.error(f"Create user failed: {e}")
        return None


def link_user_mapping(
    platform: str,
    external_id: str,
    user_id: str,
    display_name: Optional[str] = None,
    force: bool = False
) -> bool:
    platform = (platform or "").strip().lower()
    external_id = str(external_id or "").strip()
    if not platform or not external_id or not user_id:
        return False
    now = time.time()
    try:
        with _db_lock, _get_db_connection() as conn:
            row = conn.execute(
                "SELECT user_id FROM user_mappings WHERE platform = ? AND external_id = ?",
                (platform, external_id)
            ).fetchone()
            if row and row["user_id"] != user_id and not force:
                return False

            existing_user = conn.execute(
                "SELECT user_id FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if not existing_user:
                conn.execute(
                    "INSERT INTO users (user_id, display_name, created_at) VALUES (?, ?, ?)",
                    (user_id, display_name, now)
                )
            elif display_name:
                conn.execute(
                    "UPDATE users SET display_name = ? WHERE user_id = ?",
                    (display_name, user_id)
                )

            if row:
                conn.execute(
                    "UPDATE user_mappings SET user_id = ? WHERE platform = ? AND external_id = ?",
                    (user_id, platform, external_id)
                )
            else:
                conn.execute(
                    "INSERT INTO user_mappings (platform, external_id, user_id, created_at) VALUES (?, ?, ?, ?)",
                    (platform, external_id, user_id, now)
                )
    except sqlite3.Error as e:
        logger.error(f"Link user mapping failed: {e}")
        return False
    return True


def list_users() -> list[dict]:
    try:
        with _db_lock, _get_db_connection() as conn:
            rows = conn.execute(
                "SELECT user_id, display_name, created_at FROM users ORDER BY created_at"
            ).fetchall()
    except sqlite3.Error as e:
        logger.error(f"List users failed: {e}")
        return []
    return [
        {
            "user_id": row["user_id"],
            "display_name": row["display_name"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def list_user_mappings(platform: Optional[str] = None) -> list[dict]:
    platform = (platform or "").strip().lower()
    try:
        with _db_lock, _get_db_connection() as conn:
            if platform:
                rows = conn.execute(
                    "SELECT platform, external_id, user_id, created_at FROM user_mappings WHERE platform = ?",
                    (platform,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT platform, external_id, user_id, created_at FROM user_mappings"
                ).fetchall()
    except sqlite3.Error as e:
        logger.error(f"List user mappings failed: {e}")
        return []
    return [
        {
            "platform": row["platform"],
            "external_id": row["external_id"],
            "user_id": row["user_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def resolve_user_id(platform: str, external_id: str, display_name: Optional[str] = None) -> str:
    """
    获取或创建内部 user_id。
    platform: 例如 "telegram"
    external_id: 平台侧用户标识（如 chat_id）
    """
    platform = (platform or "").strip().lower()
    external_id = str(external_id or "").strip()
    if not platform or not external_id:
        return config.DEFAULT_USER_ID

    with _db_lock, _get_db_connection() as conn:
        try:
            row = conn.execute(
                "SELECT user_id FROM user_mappings WHERE platform = ? AND external_id = ?",
                (platform, external_id)
            ).fetchone()
            if row:
                user_id = row["user_id"]
                if display_name:
                    conn.execute(
                        "UPDATE users SET display_name = ? WHERE user_id = ?",
                        (display_name, user_id)
                    )
                return user_id

            user_id = _create_user_id(conn)
            now = time.time()
            conn.execute(
                "INSERT INTO users (user_id, display_name, created_at) VALUES (?, ?, ?)",
                (user_id, display_name, now)
            )
            conn.execute(
                "INSERT INTO user_mappings (platform, external_id, user_id, created_at) VALUES (?, ?, ?, ?)",
                (platform, external_id, user_id, now)
            )
            logger.info("已创建新用户映射 platform=%s external_id=%s user_id=%s", platform, external_id, user_id)
            return user_id
        except (sqlite3.Error, ValueError) as e:
            logger.error(f"用户映射失败: {e}")
            return config.DEFAULT_USER_ID


def get_external_id(user_id: str, platform: str) -> Optional[str]:
    platform = (platform or "").strip().lower()
    if not platform or not user_id:
        return None
    try:
        with _db_lock, _get_db_connection() as conn:
            row = conn.execute(
                "SELECT external_id FROM user_mappings WHERE platform = ? AND user_id = ?",
                (platform, user_id)
            ).fetchone()
    except sqlite3.Error as e:
        logger.error(f"读取用户映射失败: {e}")
        return None
    return row["external_id"] if row else None

# --- 通用文件读写 ---
def _load_meta(default: Optional[Any] = None, user_id: Optional[str] = None) -> Any:
    resolved_user_id = user_id or get_current_user_id()
    fallback = default if default is not None else {"pinned_files": []}
    try:
        with _db_lock, _get_db_connection() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE user_id = ? AND key = ?",
                (resolved_user_id, "pinned_files")
            ).fetchone()
    except sqlite3.Error as e:
        logger.error(f"读取 meta 失败: {e}")
        return fallback
    if not row:
        return fallback
    try:
        pinned_files = json.loads(row["value"]) if row["value"] else []
    except json.JSONDecodeError as e:
        logger.warning(f"meta 解析失败: {e}")
        return fallback
    return {"pinned_files": pinned_files}


def _save_meta(data: Any, user_id: Optional[str] = None) -> bool:
    if not isinstance(data, dict):
        logger.error("meta 保存失败：数据结构不是 dict")
        return False
    pinned_files = data.get("pinned_files", [])
    try:
        value = json.dumps(pinned_files, ensure_ascii=False)
    except TypeError as e:
        logger.error(f"meta 序列化失败: {e}")
        return False
    resolved_user_id = user_id or get_current_user_id()
    try:
        with _db_lock, _get_db_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (user_id, key, value) VALUES (?, ?, ?)",
                (resolved_user_id, "pinned_files", value)
            )
        return True
    except sqlite3.Error as e:
        logger.error(f"保存 meta 失败: {e}")
        return False


def _load_pending_reminders(default: Optional[Any] = None, user_id: Optional[str] = None) -> Any:
    resolved_user_id = user_id or get_current_user_id()
    fallback = default if default is not None else []
    try:
        with _db_lock, _get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, run_at, prompt FROM pending_reminders WHERE user_id = ? ORDER BY run_at",
                (resolved_user_id,)
            ).fetchall()
    except sqlite3.Error as e:
        logger.error(f"读取 pending_reminders 失败: {e}")
        return fallback
    if not rows:
        return fallback
    return [{"id": r["id"], "run_at": r["run_at"], "prompt": r["prompt"]} for r in rows]


def _save_pending_reminders(data: Any, user_id: Optional[str] = None) -> bool:
    if not isinstance(data, list):
        logger.error("pending_reminders 保存失败：数据结构不是 list")
        return False
    resolved_user_id = user_id or get_current_user_id()
    rows = [
        (r.get("id"), resolved_user_id, r.get("run_at", 0), r.get("prompt", ""))
        for r in data if r.get("id")
    ]
    try:
        with _db_lock, _get_db_connection() as conn:
            conn.execute("DELETE FROM pending_reminders WHERE user_id = ?", (resolved_user_id,))
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO pending_reminders (id, user_id, run_at, prompt) VALUES (?, ?, ?, ?)",
                    rows
                )
        return True
    except sqlite3.Error as e:
        logger.error(f"保存 pending_reminders 失败: {e}")
        return False


def _load_short_term_memory(default: Optional[Any] = None, user_id: Optional[str] = None) -> Any:
    resolved_user_id = user_id or get_current_user_id()
    fallback = default if default is not None else []
    try:
        with _db_lock, _get_db_connection() as conn:
            rows = conn.execute(
                "SELECT role, text, timestamp FROM short_term_memory WHERE user_id = ? ORDER BY id",
                (resolved_user_id,)
            ).fetchall()
    except sqlite3.Error as e:
        logger.error(f"读取 short_term_memory 失败: {e}")
        return fallback
    if not rows:
        return fallback
    return [{"role": r["role"], "text": r["text"], "timestamp": r["timestamp"]} for r in rows]


def _save_short_term_memory(data: Any, user_id: Optional[str] = None) -> bool:
    if not isinstance(data, list):
        logger.error("short_term_memory 保存失败：数据结构不是 list")
        return False
    resolved_user_id = user_id or get_current_user_id()
    rows = [
        (resolved_user_id, m.get("role", "user"), m.get("text", ""), m.get("timestamp", 0))
        for m in data
    ]
    try:
        with _db_lock, _get_db_connection() as conn:
            conn.execute("DELETE FROM short_term_memory WHERE user_id = ?", (resolved_user_id,))
            if rows:
                conn.executemany(
                    "INSERT INTO short_term_memory (user_id, role, text, timestamp) VALUES (?, ?, ?, ?)",
                    rows
                )
        return True
    except sqlite3.Error as e:
        logger.error(f"保存 short_term_memory 失败: {e}")
        return False


def load_all_pending_reminders() -> list[dict]:
    """读取所有用户的 pending_reminders（供恢复任务使用）。"""
    try:
        with _db_lock, _get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, user_id, run_at, prompt FROM pending_reminders ORDER BY run_at"
            ).fetchall()
    except sqlite3.Error as e:
        logger.error(f"读取全部 pending_reminders 失败: {e}")
        return []
    return [
        {"id": r["id"], "user_id": r["user_id"], "run_at": r["run_at"], "prompt": r["prompt"]}
        for r in rows
    ]

def load_json(file_key: str, default: Optional[Any] = None, user_id: Optional[str] = None) -> Any:
    """读取指定的 JSON 数据（线程安全）"""
    if file_key == "meta":
        return _load_meta(default, user_id)
    if file_key == "pending_reminders":
        return _load_pending_reminders(default, user_id)
    if file_key == "short_term_memory":
        return _load_short_term_memory(default, user_id)
    logger.error(f"未知的 file_key: {file_key}")
    return default if default is not None else []

def save_json(file_key: str, data: Any, user_id: Optional[str] = None) -> bool:
    """保存数据到指定的 JSON 数据（原子性写入，线程安全）"""
    if file_key == "meta":
        return _save_meta(data, user_id)
    if file_key == "pending_reminders":
        return _save_pending_reminders(data, user_id)
    if file_key == "short_term_memory":
        return _save_short_term_memory(data, user_id)
    logger.error(f"未知的 file_key: {file_key}")
    return False

# --- Amaya 记忆文件系统 API ---
def _safe_user_id(user_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", user_id or config.DEFAULT_USER_ID)


def _get_user_memory_dir(user_id: Optional[str] = None) -> str:
    resolved_user_id = _safe_user_id(user_id or get_current_user_id())
    path = os.path.join(DATA_DIR, resolved_user_id)
    os.makedirs(path, exist_ok=True)
    return path


def list_files_in_memory(user_id: Optional[str] = None) -> List[str]:
    """列出所有记忆文件"""
    try:
        dir_path = _get_user_memory_dir(user_id)
        return [f for f in os.listdir(dir_path) if not f.startswith('.')]
    except OSError as e:
        logger.error(f"列出记忆文件失败: {e}")
        return []

def read_file_content(filename: str, user_id: Optional[str] = None) -> Optional[str]:
    """读取记忆库中的文件内容"""
    dir_path = _get_user_memory_dir(user_id)
    path = os.path.join(dir_path, os.path.basename(filename)) # 安全处理
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except IOError as e:
        logger.error(f"读取文件 {filename} 失败: {e}")
        return None
    except Exception as e:
        logger.exception(f"读取文件 {filename} 异常: {e}")
        return None

def write_file_content(filename: str, content: str, user_id: Optional[str] = None) -> bool:
    """写入/覆盖记忆库中的文件内容"""
    dir_path = _get_user_memory_dir(user_id)
    path = os.path.join(dir_path, os.path.basename(filename))
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.debug(f"已写入文件: {filename}")
        return True
    except IOError as e:
        logger.error(f"写入文件 {filename} 失败: {e}")
        return False
    except Exception as e:
        logger.exception(f"写入文件 {filename} 时发生未知错误: {e}")
        return False

def _default_schedule() -> dict:
    return {
        "version": 1,
        "timezone": config.TIMEZONE,
        "days": [],
        "updated_at": datetime.now().isoformat(timespec="seconds")
    }


def build_schedule_item_id(existing_ids: Optional[set[str]] = None) -> str:
    import secrets
    existing_ids = existing_ids or set()
    while True:
        candidate = f"e{int(time.time() * 1000):x}{secrets.token_hex(2)}"
        if candidate not in existing_ids:
            return candidate


def _normalize_schedule(data: Any) -> dict:
    schedule = _default_schedule()
    if not isinstance(data, dict):
        return schedule

    timezone = data.get("timezone") or schedule["timezone"]
    schedule["timezone"] = timezone
    schedule["version"] = data.get("version", schedule["version"])

    days = data.get("days", [])
    if not isinstance(days, list):
        return schedule

    normalized_days = []
    for day in days:
        if not isinstance(day, dict):
            continue
        date_str = str(day.get("date", "")).strip()
        if not date_str:
            continue
        items = day.get("items", [])
        if not isinstance(items, list):
            items = []
        normalized_items = []
        existing_ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            item_id = str(item.get("id") or build_schedule_item_id(existing_ids))
            existing_ids.add(item_id)
            tags = item.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            normalized_items.append({
                "id": item_id,
                "start": str(item.get("start", "")).strip(),
                "end": str(item.get("end", "")).strip(),
                "title": title,
                "location": str(item.get("location", "")).strip(),
                "note": str(item.get("note", "")).strip(),
                "tags": tags
            })
        normalized_days.append({"date": date_str, "items": normalized_items})

    schedule["days"] = sorted(normalized_days, key=lambda d: d.get("date", ""))
    return schedule


def load_schedule(user_id: Optional[str] = None) -> dict:
    content = read_file_content(SCHEDULE_FILE, user_id=user_id)
    if not content:
        return _default_schedule()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"{SCHEDULE_FILE} 解析失败: {e}")
        return _default_schedule()
    return _normalize_schedule(data)


def save_schedule(schedule: dict, user_id: Optional[str] = None) -> bool:
    if not isinstance(schedule, dict):
        logger.error(f"{SCHEDULE_FILE} 保存失败：数据结构不是 dict")
        return False
    normalized = _normalize_schedule(schedule)
    normalized["updated_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        content = json.dumps(normalized, ensure_ascii=False, indent=2)
    except TypeError as e:
        logger.error(f"{SCHEDULE_FILE} 序列化失败: {e}")
        return False
    return write_file_content(SCHEDULE_FILE, content, user_id=user_id)


def _parse_schedule_date(date_str: str) -> Optional[date]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _time_to_minutes(time_str: str) -> Optional[int]:
    if not time_str:
        return None
    try:
        value = datetime.strptime(time_str, "%H:%M")
    except (TypeError, ValueError):
        return None
    return value.hour * 60 + value.minute


def _sort_schedule_items(items: list[dict]) -> list[dict]:
    def _key(item: dict) -> tuple:
        start = _time_to_minutes(item.get("start", ""))
        return (start if start is not None else 24 * 60 + 1, item.get("title", ""))
    return sorted(items, key=_key)


def _format_schedule_item(item: dict) -> str:
    parts = []
    start = item.get("start", "")
    end = item.get("end", "")
    title = item.get("title", "")
    if start and end:
        parts.append(f"{start}-{end}")
    elif start:
        parts.append(start)
    if title:
        parts.append(title)
    line = " ".join(parts) if parts else title
    location = item.get("location", "")
    if location:
        line += f" @ {location}"
    tags = item.get("tags") or []
    if tags:
        tag_str = " ".join(f"#{t}" for t in tags if t)
        if tag_str:
            line += f" {tag_str}"
    note = item.get("note", "")
    if note:
        note_preview = note[:60]
        line += f" | {note_preview}"
    item_id = item.get("id", "")
    if item_id:
        line += f" (id: {item_id})"
    return line


def get_schedule_summary(
    user_id: Optional[str] = None,
    start_date: Optional[str] = None,
    days: int = 7,
    include_empty_today: bool = True
) -> str:
    schedule = load_schedule(user_id=user_id)
    today = datetime.now().date()
    start = _parse_schedule_date(start_date) if start_date else today
    if start is None:
        start = today
    days = max(1, min(days, 14))

    day_map = {d.get("date", ""): d for d in schedule.get("days", []) if isinstance(d, dict)}
    lines = ["=== DAILY SCHEDULE ==="]
    had_any = False
    for offset in range(days):
        day = start + timedelta(days=offset)
        day_str = day.strftime("%Y-%m-%d")
        items = day_map.get(day_str, {}).get("items", [])
        include_empty = offset == 0 or (include_empty_today and day == today)
        if not items and not include_empty:
            continue
        lines.append(f"{day_str}:")
        if not items:
            lines.append("- (暂无安排)")
            continue
        had_any = True
        sorted_items = _sort_schedule_items(items)
        max_items = 10
        for item in sorted_items[:max_items]:
            lines.append(f"- {_format_schedule_item(item)}")
        if len(sorted_items) > max_items:
            lines.append(f"- ... 还有 {len(sorted_items) - max_items} 项未展示")

    if not had_any and not include_empty_today:
        return "=== DAILY SCHEDULE ===\n- (暂无安排)"
    return "\n".join(lines)

def delete_file(filename, user_id: Optional[str] = None):
    """删除记忆库中的文件"""
    dir_path = _get_user_memory_dir(user_id)
    path = os.path.join(dir_path, os.path.basename(filename))
    if os.path.exists(path):
        os.remove(path)
        toggle_pin_status(filename, pin=False, user_id=user_id)
        return True
    return False

# --- 置顶 (Pin) 逻辑 ---
def toggle_pin_status(filename, pin: bool, user_id: Optional[str] = None):
    """设置或取消置顶"""
    meta = load_json("meta", default={"pinned_files": []}, user_id=user_id)
    safe_name = os.path.basename(filename)
    if pin:
        if safe_name not in meta["pinned_files"]:
            meta["pinned_files"].append(safe_name)
    else:
        if safe_name in meta["pinned_files"]:
            meta["pinned_files"].remove(safe_name)
    save_json("meta", meta, user_id=user_id)
    return safe_name in meta["pinned_files"]

def get_pinned_content(user_id: Optional[str] = None):
    """获取所有置顶文件的内容"""
    meta = load_json("meta", default={"pinned_files": []}, user_id=user_id)
    context_str = ""
    for fname in meta["pinned_files"]:
        content = read_file_content(fname, user_id=user_id)
        if content:
            context_str += f"\n--- [Pinned Memory: {fname}] ---\n{content}\n"
    return context_str



def get_pending_reminders_summary(user_id: Optional[str] = None):
    """将挂起的闹钟任务转换为较为可读的摘要"""
    reminders = load_json("pending_reminders", default=[], user_id=user_id)
    if not reminders:
        return "无挂起的提醒任务。"

    summary = []
    now = time.time()
    for reminder in reminders:
        reminder_id = reminder.get('id', '')
        run_at = reminder.get('run_at', 0)
        prompt = reminder.get('prompt', '未知任务')

        # 计算剩余时间
        diff = int(run_at - now)
        if diff > 0:
            time_str = f"{diff}秒后"
            # 如果时间很长，显示具体日期
            if diff > 3600:
                dt = datetime.fromtimestamp(run_at)
                time_str = dt.strftime("%m-%d %H:%M")
            summary.append(f"- (ID: {reminder_id}) {prompt} (执行时间: {time_str})")

    if not summary:
        return "无挂起的提醒任务。"
    return "以下是提醒任务列表\n" + "\n".join(summary)

def get_global_context_string(user_id: Optional[str] = None):
    """
    【核心函数】
    聚合所有 Amaya 需要"默认"看见的信息。
    包括：
    1. Pinned Files (用户手动置顶)
    2. Default Files (系统默认可见，如 routine.json)
    3. Structured Schedule Summary (结构化日程表摘要)
    4. Pending Reminders (当前的提醒列表)
    """
    context_parts = []
    resolved_user_id = user_id or get_current_user_id()

    # 1. 获取 Pinned Files
    meta = load_json("meta", default={"pinned_files": []}, user_id=resolved_user_id)
    pinned_set = set(meta.get("pinned_files", []))

    # 2. 合并 Default Files (去重)
    dir_path = _get_user_memory_dir(resolved_user_id)
    for f in config.DEFAULT_VISIBLE_FILES:
        if os.path.exists(os.path.join(dir_path, f)):
            pinned_set.add(f)
    if SCHEDULE_FILE in pinned_set:
        pinned_set.remove(SCHEDULE_FILE)

    # 3. 读取并组装内容
    if pinned_set:
        context_parts.append("=== 📂 MEMORY BANK (ACTIVE FILES) ===")
        for fname in pinned_set:
            content = read_file_content(fname, user_id=resolved_user_id)
            if content:
                # 加上文件名作为标题，方便 AI 区分
                context_parts.append(f"\n--- FILE: {fname} ---\n{content}")

    # 4. 注入结构化日程表摘要
    schedule_summary = get_schedule_summary(user_id=resolved_user_id)
    if schedule_summary:
        context_parts.append(f"\n{schedule_summary}")

    # 5. 注入 Pending Reminders (这能有效防止重复设置提醒！)
    reminders_summary = get_pending_reminders_summary(user_id=resolved_user_id)
    context_parts.append(f"\n=== ACTIVE TIMERS (PENDING) ===\n{reminders_summary}")

    full_context = "\n".join(context_parts)
    if len(full_context) > config.GLOBAL_CONTEXT_MAX_CHARS:
        truncated = full_context[:config.GLOBAL_CONTEXT_MAX_CHARS]
        notice = f"[Context trimmed to {config.GLOBAL_CONTEXT_MAX_CHARS} chars]\n"
        return notice + truncated
    return full_context


# --- 事件总线读写（线程安全）---
def append_event_to_bus(event: dict, user_id: Optional[str] = None) -> bool:
    """
    线程安全地向系统事件总线追加一条事件。
    """
    resolved_user_id = user_id or get_current_user_id()
    if "user_id" not in event:
        event["user_id"] = resolved_user_id
    try:
        payload = json.dumps(event, ensure_ascii=False)
    except TypeError as e:
        logger.error(f"事件序列化失败: {e}")
        return False

    event_id = event.get("id") or event.get("reminder_id") or "-"
    event_type = event.get("type")
    resolved_user_id = event.get("user_id") or resolved_user_id
    try:
        with _db_lock, _get_db_connection() as conn:
            conn.execute(
                "INSERT INTO sys_events (user_id, event_id, event_type, payload, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (resolved_user_id, event_id, event_type, payload, "pending", time.time())
            )
    except sqlite3.Error as e:
        event_logger.error(f"事件总线写入失败: {e}")
        return False
    event_logger.debug("事件写入总线 type=%s id=%s", event_type, event_id)
    return True


def read_events_from_bus() -> tuple[list[dict], list[str]]:
    """
    线程安全地读取并清空系统事件总线。
    返回 (events, invalid_lines)。
    """
    events: list[dict] = []
    invalid_lines: list[str] = []
    try:
        with _db_lock, _get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, payload, user_id FROM sys_events WHERE status = 'pending' ORDER BY id"
            ).fetchall()
            if not rows:
                return [], []

            valid_ids: list[int] = []
            invalid_ids: list[int] = []

            for row in rows:
                payload = row["payload"]
                row_user_id = row["user_id"]
                try:
                    event = json.loads(payload)
                    if isinstance(event, dict) and "user_id" not in event:
                        event["user_id"] = row_user_id or config.DEFAULT_USER_ID
                    events.append(event)
                    valid_ids.append(row["id"])
                except json.JSONDecodeError as e:
                    event_logger.warning(f"事件解析失败: {e}")
                    invalid_lines.append(payload)
                    invalid_ids.append(row["id"])

            now = time.time()
            if valid_ids:
                placeholders = ",".join(["?"] * len(valid_ids))
                conn.execute(
                    f"UPDATE sys_events SET status = 'processed', processed_at = ? WHERE id IN ({placeholders})",
                    [now, *valid_ids]
                )
            if invalid_ids:
                placeholders = ",".join(["?"] * len(invalid_ids))
                conn.execute(
                    f"UPDATE sys_events SET status = 'invalid', processed_at = ? WHERE id IN ({placeholders})",
                    [now, *invalid_ids]
                )
    except sqlite3.Error as e:
        event_logger.error(f"读取事件总线失败: {e}")
        return [], []

    event_logger.debug("事件总线读取完成 events=%s invalid=%s", len(events), len(invalid_lines))
    return events, invalid_lines


_init_db()
