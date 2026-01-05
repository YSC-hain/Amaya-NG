import contextvars
from contextlib import contextmanager
from typing import Optional

import config

_user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "user_id",
    default=config.DEFAULT_USER_ID
)


def get_current_user_id() -> str:
    return _user_id_var.get(config.DEFAULT_USER_ID)


@contextmanager
def user_context(user_id: Optional[str]):
    """Attach user_id to current context for per-user storage access."""
    new_id = user_id or config.DEFAULT_USER_ID
    token = _user_id_var.set(new_id)
    try:
        yield new_id
    finally:
        _user_id_var.reset(token)
