# adapters/base.py
"""
消息发送抽象层 —— 使 Amaya 核心逻辑与具体平台解耦。
未来接入新平台时，只需实现 MessageSender 协议即可。
"""
from abc import ABC, abstractmethod
from typing import Optional


class MessageSender(ABC):
    """消息发送协议"""

    @abstractmethod
    async def send_text(self, text: str, parse_mode: Optional[str] = None) -> bool:
        """
        向 OWNER 发送文本消息。
        Args:
            text: 消息正文
            parse_mode: 可选的格式化模式 (如 "Markdown", "HTML")
        Returns:
            是否发送成功
        """
        ...
