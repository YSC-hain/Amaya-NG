# utils/logging_setup.py
"""
统一的日志初始化工具。
支持控制台 + 轮转文件输出，避免日志无限膨胀。
"""
import contextvars
import logging
import logging.config
import os
import uuid
from contextlib import contextmanager
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

from utils.user_context import get_current_user_id

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def generate_request_id() -> str:
    """Generate a short request id for log correlation."""
    return uuid.uuid4().hex[:12]


def get_request_id() -> str:
    """Get current request id from context."""
    return _request_id_var.get("-")


@contextmanager
def request_context(request_id: Optional[str] = None):
    """Attach a request id to the current context for structured logging."""
    new_id = request_id or generate_request_id()
    token = _request_id_var.set(new_id)
    try:
        yield new_id
    finally:
        _request_id_var.reset(token)


class RequestIdFilter(logging.Filter):
    """Inject request_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get("-")
        record.user_id = get_current_user_id()
        return True


class SizedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Timed rotation with optional size cap."""

    def __init__(
        self,
        filename: str,
        when: str = "D",
        interval: int = 1,
        backupCount: int = 7,
        encoding: Optional[str] = None,
        delay: bool = False,
        utc: bool = False,
        max_bytes: int = 0
    ):
        self.max_bytes = max_bytes
        super().__init__(
            filename,
            when=when,
            interval=interval,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            utc=utc
        )

    def shouldRollover(self, record: logging.LogRecord) -> int:
        if self.max_bytes:
            if self.stream is None:
                self.stream = self._open()
            self.stream.seek(0, os.SEEK_END)
            if self.stream.tell() >= self.max_bytes:
                return 1
        return super().shouldRollover(record)


def setup_logging(
    log_dir: str = "data/logs",
    level: int = logging.INFO,
    retention_days: int = 7,
    max_bytes: int = 0,
    payload_max_bytes: int = 0,
) -> str:
    """
    初始化日志配置（控制台 + 多文件轮转）。

    Args:
        log_dir: 日志目录。
        level: 根日志级别。
        retention_days: 保留天数（按天分割）。
        max_bytes: 单个日志文件的最大大小（字节），0 表示不限制。
        payload_max_bytes: Payload 日志的单文件大小上限，0 表示不限制。

    Returns:
        主日志文件路径。
    """
    os.makedirs(log_dir, exist_ok=True)
    app_log_path = os.path.join(log_dir, "amaya.app.log")
    llm_log_path = os.path.join(log_dir, "amaya.llm.log")
    event_log_path = os.path.join(log_dir, "amaya.events.log")
    error_log_path = os.path.join(log_dir, "amaya.error.log")
    payload_log_path = os.path.join(log_dir, "amaya.llm.payload.log")

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {
                "()": RequestIdFilter,
            }
        },
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(levelname)s - %(name)s - %(request_id)s - %(user_id)s - %(message)s"
            },
            "payload": {
                "format": "%(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "level": level,
                "filters": ["request_id"],
            },
            "app_file": {
                "()": "utils.logging_setup.SizedTimedRotatingFileHandler",
                "formatter": "standard",
                "level": level,
                "filename": app_log_path,
                "when": "D",
                "interval": 1,
                "backupCount": retention_days,
                "max_bytes": max_bytes,
                "filters": ["request_id"],
                "encoding": "utf-8"
            },
            "llm_file": {
                "()": "utils.logging_setup.SizedTimedRotatingFileHandler",
                "formatter": "standard",
                "level": level,
                "filename": llm_log_path,
                "when": "D",
                "interval": 1,
                "backupCount": retention_days,
                "max_bytes": max_bytes,
                "filters": ["request_id"],
                "encoding": "utf-8"
            },
            "event_file": {
                "()": "utils.logging_setup.SizedTimedRotatingFileHandler",
                "formatter": "standard",
                "level": level,
                "filename": event_log_path,
                "when": "D",
                "interval": 1,
                "backupCount": retention_days,
                "max_bytes": max_bytes,
                "filters": ["request_id"],
                "encoding": "utf-8"
            },
            "error_file": {
                "()": "utils.logging_setup.SizedTimedRotatingFileHandler",
                "formatter": "standard",
                "level": logging.WARNING,
                "filename": error_log_path,
                "when": "D",
                "interval": 1,
                "backupCount": retention_days,
                "max_bytes": max_bytes,
                "filters": ["request_id"],
                "encoding": "utf-8"
            },
            "payload_file": {
                "()": "utils.logging_setup.SizedTimedRotatingFileHandler",
                "formatter": "payload",
                "level": logging.INFO,
                "filename": payload_log_path,
                "when": "D",
                "interval": 1,
                "backupCount": retention_days,
                "max_bytes": payload_max_bytes,
                "encoding": "utf-8"
            }
        },
        "loggers": {
            "Amaya.LLM": {
                "handlers": ["llm_file"],
                "level": level,
                "propagate": True
            },
            "Amaya.EventBus": {
                "handlers": ["event_file"],
                "level": level,
                "propagate": True
            },
            "Amaya.LLM.Payload": {
                "handlers": ["payload_file"],
                "level": logging.INFO,
                "propagate": False
            }
        },
        "root": {
            "level": level,
            "handlers": ["console", "app_file", "error_file"]
        }
    })

    return app_log_path


def set_library_log_levels(level: Optional[int] = logging.WARNING):
    """
    调整第三方库的日志级别，减少噪声。
    """
    noisy_loggers = [
        "apscheduler",
        "httpx",
        "google.genai",
        "telegram.ext._application"
    ]
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(level)
