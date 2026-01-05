# utils/memory_storage.py
"""
记忆文件系统操作
处理用户记忆目录的文件读写
"""

import json
import os
import logging
import re
from typing import Optional, List

import config
from utils.user_context import get_current_user_id

logger = logging.getLogger("Amaya.MemoryStorage")

# 记忆库物理路径
DATA_DIR = "data/memory_bank"
os.makedirs(DATA_DIR, exist_ok=True)


def _safe_user_id(user_id: str) -> str:
    """清理 user_id 中的特殊字符"""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", user_id or config.DEFAULT_USER_ID)


def get_user_memory_dir(user_id: Optional[str] = None) -> str:
    """获取用户记忆目录路径（自动创建）"""
    resolved_user_id = _safe_user_id(user_id or get_current_user_id())
    path = os.path.join(DATA_DIR, resolved_user_id)
    os.makedirs(path, exist_ok=True)
    return path


def list_files_in_memory(user_id: Optional[str] = None) -> List[str]:
    """列出所有记忆文件"""
    try:
        dir_path = get_user_memory_dir(user_id)
        return [f for f in os.listdir(dir_path) if not f.startswith('.')]
    except OSError as e:
        logger.error(f"列出记忆文件失败: {e}")
        return []


def read_file_content(filename: str, user_id: Optional[str] = None) -> Optional[str]:
    """读取记忆库中的文件内容"""
    dir_path = get_user_memory_dir(user_id)
    path = os.path.join(dir_path, os.path.basename(filename))  # 安全处理
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
    dir_path = get_user_memory_dir(user_id)
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


def delete_file(filename: str, user_id: Optional[str] = None) -> bool:
    """删除记忆库中的文件"""
    dir_path = get_user_memory_dir(user_id)
    path = os.path.join(dir_path, os.path.basename(filename))
    if os.path.exists(path):
        try:
            os.remove(path)
            logger.debug(f"已删除文件: {filename}")
            return True
        except OSError as e:
            logger.error(f"删除文件 {filename} 失败: {e}")
            return False
    return False
