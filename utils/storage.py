# utils/storage.py
import json
import os
import logging
import sqlite3
import threading
import re
import uuid
from datetime import datetime
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
_legacy_memory_migrated = False

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

    _migrate_schema()
    _migrate_json_to_db()


def _get_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _migrate_schema() -> None:
    with _db_lock, _get_db_connection() as conn:
        # meta table migration (add user_id dimension)
        cols = _get_table_columns(conn, "meta")
        if cols and "user_id" not in cols:
            conn.execute("ALTER TABLE meta RENAME TO meta_legacy")
            conn.execute("""
                CREATE TABLE meta (
                    user_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                )
            """)
            conn.execute(
                "INSERT INTO meta (user_id, key, value) SELECT ?, key, value FROM meta_legacy",
                (config.DEFAULT_USER_ID,)
            )
            conn.execute("DROP TABLE meta_legacy")

        for table in ("pending_reminders", "short_term_memory", "sys_events"):
            cols = _get_table_columns(conn, table)
            if cols and "user_id" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")
                conn.execute(
                    f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL",
                    (config.DEFAULT_USER_ID,)
                )


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
                "INSERT OR REPLACE INTO meta (user_id, key, value) VALUES (?, ?, ?)",
                (config.DEFAULT_USER_ID, "pinned_files", json.dumps(pinned_files, ensure_ascii=False))
            )
            logger.info("已迁移 meta.json -> SQLite")

        if pending_count == 0 and os.path.exists(FILES["pending_reminders"]):
            reminders = _load_json_file(FILES["pending_reminders"], default=[]) or []
            rows = [
                (r.get("id"), config.DEFAULT_USER_ID, r.get("run_at", 0), r.get("prompt", ""))
                for r in reminders if r.get("id")
            ]
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO pending_reminders (id, user_id, run_at, prompt) VALUES (?, ?, ?, ?)",
                    rows
                )
            logger.info("已迁移 pending_reminders.json -> SQLite")

        if memory_count == 0 and os.path.exists(FILES["short_term_memory"]):
            memory = _load_json_file(FILES["short_term_memory"], default=[]) or []
            rows = [
                (config.DEFAULT_USER_ID, m.get("role", "user"), m.get("text", ""), m.get("timestamp", 0))
                for m in memory
            ]
            if rows:
                conn.executemany(
                    "INSERT INTO short_term_memory (user_id, role, text, timestamp) VALUES (?, ?, ?, ?)",
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
                event_user_id = config.DEFAULT_USER_ID
                payload = line.strip()
                try:
                    event = json.loads(line)
                    event_type = event.get("type")
                    event_id = event.get("id") or event.get("reminder_id")
                    event_user_id = event.get("user_id") or config.DEFAULT_USER_ID
                    payload = json.dumps(event, ensure_ascii=False)
                except json.JSONDecodeError:
                    status = "invalid"
                conn.execute(
                    "INSERT INTO sys_events (user_id, event_id, event_type, payload, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (event_user_id, event_id, event_type, payload, status, time.time())
                )
            if lines:
                logger.info("已迁移 sys_event_bus.jsonl -> SQLite")

# --- 用户映射 ---
def _create_user_id() -> str:
    return uuid.uuid4().hex


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


def create_user(display_name: Optional[str] = None, user_id: Optional[str] = None) -> str:
    resolved_user_id = user_id or _create_user_id()
    now = time.time()
    try:
        with _db_lock, _get_db_connection() as conn:
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
    except sqlite3.Error as e:
        logger.error(f"Create user failed: {e}")
        return config.DEFAULT_USER_ID
    return resolved_user_id


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

            user_id = _create_user_id()
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
        except sqlite3.Error as e:
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
    """读取指定的 JSON 文件（线程安全）"""
    if file_key == "meta":
        return _load_meta(default, user_id)
    if file_key == "pending_reminders":
        return _load_pending_reminders(default, user_id)
    if file_key == "short_term_memory":
        return _load_short_term_memory(default, user_id)

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

def save_json(file_key: str, data: Any, user_id: Optional[str] = None) -> bool:
    """保存数据到指定的 JSON 文件（原子性写入，线程安全）"""
    if file_key == "meta":
        return _save_meta(data, user_id)
    if file_key == "pending_reminders":
        return _save_pending_reminders(data, user_id)
    if file_key == "short_term_memory":
        return _save_short_term_memory(data, user_id)

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
def _safe_user_id(user_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", user_id or config.DEFAULT_USER_ID)


def _migrate_legacy_default_memory_dir() -> None:
    global _legacy_memory_migrated
    if _legacy_memory_migrated:
        return
    _legacy_memory_migrated = True

    default_dir = os.path.join(DATA_DIR, _safe_user_id(config.DEFAULT_USER_ID))
    os.makedirs(default_dir, exist_ok=True)
    try:
        legacy_files = [
            name for name in os.listdir(DATA_DIR)
            if not name.startswith(".") and os.path.isfile(os.path.join(DATA_DIR, name))
        ]
    except OSError:
        return

    if not legacy_files:
        return

    try:
        existing_files = {
            name for name in os.listdir(default_dir)
            if not name.startswith(".") and os.path.isfile(os.path.join(default_dir, name))
        }
    except OSError:
        existing_files = set()

    for name in legacy_files:
        src = os.path.join(DATA_DIR, name)
        dst = os.path.join(default_dir, name)
        if name in existing_files:
            logger.warning("Skip legacy memory file due to conflict: %s", name)
            continue
        try:
            os.replace(src, dst)
            logger.info("Migrated legacy memory file to default user dir: %s", name)
        except OSError as e:
            logger.warning("Failed to migrate legacy memory file %s: %s", name, e)


def _get_user_memory_dir(user_id: Optional[str] = None) -> str:
    resolved_user_id = _safe_user_id(user_id or get_current_user_id())
    if resolved_user_id == _safe_user_id(config.DEFAULT_USER_ID):
        _migrate_legacy_default_memory_dir()
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
    2. Default Files (系统默认可见，如 routine.md)
    3. Pending Reminders (当前的提醒列表)
    4. etc
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

    # 3. 读取并组装内容
    if pinned_set:
        context_parts.append("=== 📂 MEMORY BANK (ACTIVE FILES) ===")
        for fname in pinned_set:
            content = read_file_content(fname, user_id=resolved_user_id)
            if content:
                # 加上文件名作为标题，方便 AI 区分
                context_parts.append(f"\n--- FILE: {fname} ---\n{content}")

    # 4. 注入 Pending Reminders (这能有效防止重复设置提醒！)
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
