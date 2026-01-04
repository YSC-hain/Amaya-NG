# utils/logging_setup.py
"""
统一的日志初始化工具。
支持控制台 + 轮转文件输出，避免日志无限膨胀。
"""
import logging
import logging.config
import os
from logging.handlers import RotatingFileHandler
from typing import Optional


def setup_logging(
    log_dir: str = "data/logs",
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> str:
    """
    初始化日志配置（控制台 + 轮转文件）。

    Args:
        log_dir: 日志目录。
        level: 根日志级别。
        max_bytes: 单个日志文件的最大大小（字节）。
        backup_count: 轮转备份数量。

    Returns:
        实际的日志文件路径。
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "amaya.log")

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "level": level,
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "standard",
                "level": level,
                "filename": log_path,
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "encoding": "utf-8"
            }
        },
        "root": {
            "level": level,
            "handlers": ["console", "file"]
        }
    })

    return log_path


def set_library_log_levels(level: Optional[int] = logging.WARNING):
    """
    调整第三方库的日志级别，减少噪声。
    """
    noisy_loggers = [
        "apscheduler",
        "httpx",
        "google.genai",
        "telegram.ext._application",
        "openai",
    ]
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(level)
