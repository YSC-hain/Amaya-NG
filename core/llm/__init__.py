# core/llm/__init__.py
"""
LLM Provider Abstraction Layer
支持多种 LLM 后端（Gemini, OpenAI 等）
"""

from core.llm.base import LLMProvider, ChatMessage, ChatResponse, MultimodalInput
from core.llm.factory import create_llm_provider

__all__ = [
    "LLMProvider",
    "ChatMessage",
    "ChatResponse",
    "MultimodalInput",
    "create_llm_provider",
]
