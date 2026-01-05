# utils/storage.py
import json
import os
import logging
import sqlite3
import threading
from datetime import datetime
import time
from typing import Any, Optional, List
import config

logger = logging.getLogger("Amaya.Storage")
event_logger = logging.getLogger("Amaya.EventBus")


def build_reminder_id(run_at: float) -> str:
    """基于时间戳和随机熵生成短 ID，避免同秒冲突。"""
    import secrets
    ts_part = format(int(run_at * 1000), 'x')[-8:]
    rand_part = secrets.token_hex(3)
    return f"r{ts_part}{rand_part}"


# 全局文件锁，防止并发读写
_file_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()  # 保护 _file_locks 的锁

def _get_file_lock(path: str) -> threading.Lock:
    """获取指定文件的锁"""
    with _locks_lock:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]

# 定义记忆库的物理路径
DATA_DIR = "data/memory_bank"
os.makedirs(DATA_DIR, exist_ok=True)

# --- 文件路径注册表 ---
# 集中管理所有数据文件路径
FILES = {
    "meta": os.path.join("data", "meta.json"),
    "pending_reminders": os.path.join("data", "pending_reminders.json"),
    "sys_bus": os.path.join("data", "sys_event_bus.jsonl"),
    "short_term_memory": os.path.join("data", "short_term_memory.json")
}

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


def _load_json_file(path: str, default: Optional[Any] = None) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失败 {path}: {e}")
        return default
    except IOError as e:
        logger.warning(f"读取文件失败 {path}: {e}")
        return default


def _init_db() -> None:
    with _db_lock, _get_db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_reminders (
                id TEXT PRIMARY KEY,
                run_at REAL NOT NULL,
                prompt TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS short_term_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sys_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    _migrate_json_to_db()


def _migrate_json_to_db() -> None:
    """
    将旧版 JSON 文件迁移到 SQLite（仅在表为空时执行）。
    保留原文件以便回滚/审计。
    """
    with _db_lock, _get_db_connection() as conn:
        meta_count = conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
        pending_count = conn.execute("SELECT COUNT(*) FROM pending_reminders").fetchone()[0]
        memory_count = conn.execute("SELECT COUNT(*) FROM short_term_memory").fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM sys_events").fetchone()[0]

        if meta_count == 0 and os.path.exists(FILES["meta"]):
            meta = _load_json_file(FILES["meta"], default={}) or {}
            pinned_files = meta.get("pinned_files", [])
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                ("pinned_files", json.dumps(pinned_files, ensure_ascii=False))
            )
            logger.info("已迁移 meta.json -> SQLite")

        if pending_count == 0 and os.path.exists(FILES["pending_reminders"]):
            reminders = _load_json_file(FILES["pending_reminders"], default=[]) or []
            rows = [
                (r.get("id"), r.get("run_at", 0), r.get("prompt", ""))
                for r in reminders if r.get("id")
            ]
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO pending_reminders (id, run_at, prompt) VALUES (?, ?, ?)",
                    rows
                )
            logger.info("已迁移 pending_reminders.json -> SQLite")

        if memory_count == 0 and os.path.exists(FILES["short_term_memory"]):
            memory = _load_json_file(FILES["short_term_memory"], default=[]) or []
            rows = [
                (m.get("role", "user"), m.get("text", ""), m.get("timestamp", 0))
                for m in memory
            ]
            if rows:
                conn.executemany(
                    "INSERT INTO short_term_memory (role, text, timestamp) VALUES (?, ?, ?)",
                    rows
                )
            logger.info("已迁移 short_term_memory.json -> SQLite")

        if event_count == 0 and os.path.exists(FILES["sys_bus"]):
            try:
                with open(FILES["sys_bus"], "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except IOError as e:
                logger.warning(f"读取 sys_event_bus 失败: {e}")
                lines = []

            for line in lines:
                if not line.strip():
                    continue
                event_type = None
                event_id = None
                status = "pending"
                payload = line.strip()
                try:
                    event = json.loads(line)
                    event_type = event.get("type")
                    event_id = event.get("id") or event.get("reminder_id")
                    payload = json.dumps(event, ensure_ascii=False)
                except json.JSONDecodeError:
                    status = "invalid"
                conn.execute(
                    "INSERT INTO sys_events (event_id, event_type, payload, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    (event_id, event_type, payload, status, time.time())
                )
            if lines:
                logger.info("已迁移 sys_event_bus.jsonl -> SQLite")

# --- 通用文件读写 ---
def _load_meta(default: Optional[Any] = None) -> Any:
    fallback = default if default is not None else {"pinned_files": []}
    try:
        with _db_lock, _get_db_connection() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", ("pinned_files",)).fetchone()
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


def _save_meta(data: Any) -> bool:
    if not isinstance(data, dict):
        logger.error("meta 保存失败：数据结构不是 dict")
        return False
    pinned_files = data.get("pinned_files", [])
    try:
        value = json.dumps(pinned_files, ensure_ascii=False)
    except TypeError as e:
        logger.error(f"meta 序列化失败: {e}")
        return False
    try:
        with _db_lock, _get_db_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                ("pinned_files", value)
            )
        return True
    except sqlite3.Error as e:
        logger.error(f"保存 meta 失败: {e}")
        return False


def _load_pending_reminders(default: Optional[Any] = None) -> Any:
    fallback = default if default is not None else []
    try:
        with _db_lock, _get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, run_at, prompt FROM pending_reminders ORDER BY run_at"
            ).fetchall()
    except sqlite3.Error as e:
        logger.error(f"读取 pending_reminders 失败: {e}")
        return fallback
    if not rows:
        return fallback
    return [{"id": r["id"], "run_at": r["run_at"], "prompt": r["prompt"]} for r in rows]


def _save_pending_reminders(data: Any) -> bool:
    if not isinstance(data, list):
        logger.error("pending_reminders 保存失败：数据结构不是 list")
        return False
    rows = [
        (r.get("id"), r.get("run_at", 0), r.get("prompt", ""))
        for r in data if r.get("id")
    ]
    try:
        with _db_lock, _get_db_connection() as conn:
            conn.execute("DELETE FROM pending_reminders")
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO pending_reminders (id, run_at, prompt) VALUES (?, ?, ?)",
                    rows
                )
        return True
    except sqlite3.Error as e:
        logger.error(f"保存 pending_reminders 失败: {e}")
        return False


def _load_short_term_memory(default: Optional[Any] = None) -> Any:
    fallback = default if default is not None else []
    try:
        with _db_lock, _get_db_connection() as conn:
            rows = conn.execute(
                "SELECT role, text, timestamp FROM short_term_memory ORDER BY id"
            ).fetchall()
    except sqlite3.Error as e:
        logger.error(f"读取 short_term_memory 失败: {e}")
        return fallback
    if not rows:
        return fallback
    return [{"role": r["role"], "text": r["text"], "timestamp": r["timestamp"]} for r in rows]


def _save_short_term_memory(data: Any) -> bool:
    if not isinstance(data, list):
        logger.error("short_term_memory 保存失败：数据结构不是 list")
        return False
    rows = [
        (m.get("role", "user"), m.get("text", ""), m.get("timestamp", 0))
        for m in data
    ]
    try:
        with _db_lock, _get_db_connection() as conn:
            conn.execute("DELETE FROM short_term_memory")
            if rows:
                conn.executemany(
                    "INSERT INTO short_term_memory (role, text, timestamp) VALUES (?, ?, ?)",
                    rows
                )
        return True
    except sqlite3.Error as e:
        logger.error(f"保存 short_term_memory 失败: {e}")
        return False


def load_json(file_key: str, default: Optional[Any] = None) -> Any:
    """读取指定的 JSON 文件（线程安全）"""
    if file_key == "meta":
        return _load_meta(default)
    if file_key == "pending_reminders":
        return _load_pending_reminders(default)
    if file_key == "short_term_memory":
        return _load_short_term_memory(default)

    path = FILES.get(file_key)
    if not path or not os.path.exists(path):
        return default if default is not None else []

    lock = _get_file_lock(path)
    with lock:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败 {path}: {e}")
            return default if default is not None else []
        except IOError as e:
            logger.warning(f"读取文件失败 {path}: {e}")
            return default if default is not None else []

def save_json(file_key: str, data: Any) -> bool:
    """保存数据到指定的 JSON 文件（原子性写入，线程安全）"""
    if file_key == "meta":
        return _save_meta(data)
    if file_key == "pending_reminders":
        return _save_pending_reminders(data)
    if file_key == "short_term_memory":
        return _save_short_term_memory(data)

    path = FILES.get(file_key)
    if not path:
        logger.error(f"未知的 file_key: {file_key}")
        return False

    lock = _get_file_lock(path)
    temp_path = path + ".tmp"

    with lock:
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # 原子性替换（Windows 需要先删除目标文件）
            if os.path.exists(path):
                os.replace(temp_path, path)
            else:
                os.rename(temp_path, path)
            return True
        except IOError as e:
            logger.error(f"保存 {path} 失败: {e}")
            # 清理临时文件
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            return False
        except TypeError as e:
            logger.error(f"JSON 序列化失败 {path}: {e}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            return False

# --- Amaya 记忆文件系统 API ---
def list_files_in_memory() -> List[str]:
    """列出所有记忆文件"""
    try:
        return [f for f in os.listdir(DATA_DIR) if not f.startswith('.')]
    except OSError as e:
        logger.error(f"列出记忆文件失败: {e}")
        return []

def read_file_content(filename: str) -> Optional[str]:
    """读取记忆库中的文件内容"""
    path = os.path.join(DATA_DIR, os.path.basename(filename)) # 安全处理
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

def write_file_content(filename: str, content: str) -> bool:
    """写入/覆盖记忆库中的文件内容"""
    path = os.path.join(DATA_DIR, os.path.basename(filename))
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

def delete_file(filename):
    """删除记忆库中的文件"""
    path = os.path.join(DATA_DIR, os.path.basename(filename))
    if os.path.exists(path):
        os.remove(path)
        toggle_pin_status(filename, pin=False)
        return True
    return False

# --- 置顶 (Pin) 逻辑 ---
def toggle_pin_status(filename, pin: bool):
    """设置或取消置顶"""
    meta = load_json("meta", default={"pinned_files": []})
    safe_name = os.path.basename(filename)
    if pin:
        if safe_name not in meta["pinned_files"]:
            meta["pinned_files"].append(safe_name)
    else:
        if safe_name in meta["pinned_files"]:
            meta["pinned_files"].remove(safe_name)
    save_json("meta", meta)
    return safe_name in meta["pinned_files"]

def get_pinned_content():
    """获取所有置顶文件的内容"""
    meta = load_json("meta", default={"pinned_files": []})
    context_str = ""
    for fname in meta["pinned_files"]:
        content = read_file_content(fname)
        if content:
            context_str += f"\n--- [Pinned Memory: {fname}] ---\n{content}\n"
    return context_str



# 定义哪些文件是 Amaya "睁眼" 就应该看见的 (即使没有被 Pin)
DEFAULT_VISIBLE_FILES = ["routine.json", "plan.md", "user_profile.md", "current_goals.md"]

def get_pending_reminders_summary():
    """将挂起的闹钟任务转换为较为可读的摘要"""
    reminders = load_json("pending_reminders", default=[])
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

def get_global_context_string():
    """
    【核心函数】
    聚合所有 Amaya 需要"默认"看见的信息。
    包括：
    1. Pinned Files (用户手动置顶)
    2. Default Files (系统默认可见，如 routine.md)
    3. Pending Reminders (当前的提醒列表)
    4. etc
    """
    context_parts = []

    # 1. 获取 Pinned Files
    meta = load_json("meta", default={"pinned_files": []})
    pinned_set = set(meta.get("pinned_files", []))

    # 2. 合并 Default Files (去重)
    for f in DEFAULT_VISIBLE_FILES:
        if os.path.exists(os.path.join(DATA_DIR, f)):
            pinned_set.add(f)

    # 3. 读取并组装内容
    if pinned_set:
        context_parts.append("=== 📂 MEMORY BANK (ACTIVE FILES) ===")
        for fname in pinned_set:
            content = read_file_content(fname)
            if content:
                # 加上文件名作为标题，方便 AI 区分
                context_parts.append(f"\n--- FILE: {fname} ---\n{content}")

    # 4. 注入 Pending Reminders (这能有效防止重复设置提醒！)
    reminders_summary = get_pending_reminders_summary()
    context_parts.append(f"\n=== ACTIVE TIMERS (PENDING) ===\n{reminders_summary}")

    full_context = "\n".join(context_parts)
    if len(full_context) > config.GLOBAL_CONTEXT_MAX_CHARS:
        truncated = full_context[:config.GLOBAL_CONTEXT_MAX_CHARS]
        notice = f"[Context trimmed to {config.GLOBAL_CONTEXT_MAX_CHARS} chars]\n"
        return notice + truncated
    return full_context


# --- 事件总线读写（线程安全）---
def append_event_to_bus(event: dict) -> bool:
    """
    线程安全地向系统事件总线追加一条事件。
    """
    try:
        payload = json.dumps(event, ensure_ascii=False)
    except TypeError as e:
        logger.error(f"事件序列化失败: {e}")
        return False

    event_id = event.get("id") or event.get("reminder_id") or "-"
    event_type = event.get("type")
    try:
        with _db_lock, _get_db_connection() as conn:
            conn.execute(
                "INSERT INTO sys_events (event_id, event_type, payload, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, event_type, payload, "pending", time.time())
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
                "SELECT id, payload FROM sys_events WHERE status = 'pending' ORDER BY id"
            ).fetchall()
            if not rows:
                return [], []

            valid_ids: list[int] = []
            invalid_ids: list[int] = []

            for row in rows:
                payload = row["payload"]
                try:
                    events.append(json.loads(payload))
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
