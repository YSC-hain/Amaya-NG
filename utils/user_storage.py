# utils/user_storage.py
"""
用户管理存储层
处理用户创建、查询、平台映射等
"""

import logging
import sqlite3
import time
from typing import Optional

import config
from utils.db import get_db_connection, get_db_lock

logger = logging.getLogger("Amaya.UserStorage")

_db_lock = get_db_lock()
_get_db_connection = get_db_connection


def _create_user_id(conn: sqlite3.Connection) -> str:
    """生成下一个可用的用户 ID（6 位数字）"""
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
    """根据平台和外部 ID 查找内部 user_id"""
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
    """创建新用户"""
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
    """绑定平台 ID 到内部 user_id"""
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
    """列出所有用户"""
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
    """列出用户映射"""
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
    """根据内部 user_id 获取平台外部 ID"""
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
