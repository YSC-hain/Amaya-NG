# utils/db.py
"""
SQLite 数据库基础设施
提供连接池、锁和表初始化
"""

import os
import sqlite3
import threading
import logging

import config

logger = logging.getLogger("Amaya.DB")

# --- SQLite 配置 ---
DB_PATH = config.DB_PATH
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

# 线程锁，确保并发安全
_db_lock = threading.Lock()


def get_db_connection() -> sqlite3.Connection:
    """获取数据库连接（线程安全）"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def get_db_lock() -> threading.Lock:
    """获取数据库锁"""
    return _db_lock


def init_db() -> None:
    """初始化数据库表结构"""
    with _db_lock, get_db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")

        # 用户表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                display_name TEXT,
                created_at REAL NOT NULL
            )
        """)

        # 用户映射表（平台 ID -> 内部 user_id）
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

        # 用户元数据表（如 pinned_files）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            )
        """)

        # 待执行提醒表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_reminders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                run_at REAL NOT NULL,
                prompt TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_reminders_user ON pending_reminders(user_id)")

        # 短期记忆表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS short_term_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_user ON short_term_memory(user_id)")

        # 系统事件表
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

        logger.debug("数据库表初始化完成")


# 模块加载时自动初始化
init_db()
