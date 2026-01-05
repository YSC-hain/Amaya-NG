# core/llm/base.py
"""
LLM Provider 抽象基类
定义所有 LLM 提供者必须实现的接口
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Callable, Any
from enum import Enum


class MessageRole(Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class ChatMessage:
    """统一的消息格式"""
    role: MessageRole
    text: str
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "text": self.text,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatMessage":
        role_str = data.get("role", "user")
        # 兼容旧格式：model -> assistant
        if role_str == "model":
            role_str = "assistant"
        return cls(
            role=MessageRole(role_str),
            text=data.get("text", ""),
            timestamp=data.get("timestamp", 0.0)
        )


@dataclass
class ChatResponse:
    """统一的响应格式"""
    text: str
    success: bool = True
    error_message: str = ""
    raw_response: Any = None  # 保留原始响应供调试


@dataclass
class MultimodalInput:
    """多模态输入"""
    text: str
    image_bytes: bytes = b''
    audio_bytes: bytes = b''
    audio_mime: str = "audio/ogg"


class LLMProvider(ABC):
    """
    LLM 提供者抽象基类
    所有具体的 LLM 实现（Gemini, OpenAI 等）都必须继承此类
    """

    def __init__(self, smart_model: str, fast_model: str):
        self.smart_model = smart_model
        self.fast_model = fast_model

    @abstractmethod
    def chat(
        self,
        messages: List[ChatMessage],
        system_instruction: str,
        multimodal_input: Optional[MultimodalInput] = None,
        tools: Optional[List[Callable]] = None,
        use_smart_model: bool = False,
        max_tool_calls: int = 10
    ) -> ChatResponse:
        """
        发送消息并获取响应

        Args:
            messages: 历史消息列表
            system_instruction: 系统提示词
            multimodal_input: 多模态输入（文本、图片、音频）
            tools: 可用的工具函数列表
            use_smart_model: 是否使用更强大的模型
            max_tool_calls: 最大工具调用次数

        Returns:
            ChatResponse: 统一格式的响应
        """
        pass

    @abstractmethod
    def get_model_name(self, use_smart: bool = False) -> str:
        """获取当前使用的模型名称"""
        pass

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        audio_mime: str,
        model: Optional[str] = None
    ) -> Optional[str]:
        """
        可选：将音频转为文本。
        默认返回 None，表示该 Provider 不支持转写。
        """
        return None

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """返回提供者名称（如 'gemini', 'openai'）"""
        pass
