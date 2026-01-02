# core/llm/factory.py
"""
LLM Provider 工厂
根据配置创建相应的 LLM 提供者实例
"""

import logging
from typing import Optional

from core.llm.base import LLMProvider

logger = logging.getLogger("Amaya.LLM.Factory")


def create_llm_provider(
    provider_type: str,
    api_key: str,
    smart_model: str,
    fast_model: str,
    api_base: Optional[str] = None
) -> LLMProvider:
    """
    工厂函数：根据配置创建 LLM 提供者

    Args:
        provider_type: 提供者类型 ("gemini" 或 "openai")
        api_key: API 密钥
        smart_model: 高级模型名称
        fast_model: 快速模型名称
        api_base: 自定义 API 基础 URL（可选）

    Returns:
        LLMProvider: 对应的 LLM 提供者实例

    Raises:
        ValueError: 如果提供者类型不支持
    """
    provider_type = provider_type.lower().strip()

    if provider_type == "gemini":
        from core.llm.gemini import GeminiProvider
        return GeminiProvider(
            api_key=api_key,
            smart_model=smart_model,
            fast_model=fast_model,
            api_base=api_base
        )

    elif provider_type in ("openai", "chatgpt"):
        from core.llm.openai import OpenAIProvider
        return OpenAIProvider(
            api_key=api_key,
            smart_model=smart_model,
            fast_model=fast_model,
            api_base=api_base
        )

    else:
        supported = ["gemini", "openai"]
        raise ValueError(
            f"不支持的 LLM 提供者: {provider_type}。"
            f"支持的提供者: {', '.join(supported)}"
        )
