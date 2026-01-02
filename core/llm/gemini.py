# core/llm/gemini.py
"""
Gemini LLM Provider 实现
"""

import logging
import io
from typing import List, Optional, Callable

import PIL.Image
from google import genai
from google.genai import types

from core.llm.base import (
    LLMProvider,
    ChatMessage,
    ChatResponse,
    MultimodalInput,
    MessageRole
)

logger = logging.getLogger("Amaya.LLM.Gemini")


class GeminiProvider(LLMProvider):
    """Gemini API 提供者"""

    def __init__(
        self,
        api_key: str,
        smart_model: str = "gemini-2.5-pro",
        fast_model: str = "gemini-2.5-flash",
        api_base: Optional[str] = None
    ):
        super().__init__(smart_model, fast_model)

        # 配置 HTTP 选项 (代理)
        http_options = None
        if api_base:
            http_options = types.HttpOptions(
                base_url=api_base,
                api_version="v1beta"
            )

        # 初始化客户端
        self.client = genai.Client(
            api_key=api_key,
            http_options=http_options
        )

        logger.info(f"Gemini Provider 初始化完成，Smart: {smart_model}, Fast: {fast_model}")

    @property
    def provider_name(self) -> str:
        return "gemini"

    def get_model_name(self, use_smart: bool = False) -> str:
        return self.smart_model if use_smart else self.fast_model

    def _convert_history_to_gemini_format(self, messages: List[ChatMessage]) -> List[dict]:
        """将统一消息格式转换为 Gemini 格式"""
        formatted_history = []
        for msg in messages:
            # Gemini 使用 "user" 和 "model" 作为角色
            role = "user" if msg.role == MessageRole.USER else "model"
            formatted_history.append({
                "role": role,
                "parts": [{"text": msg.text}]
            })
        return formatted_history

    def _build_multimodal_parts(self, multimodal_input: MultimodalInput) -> list:
        """构建多模态输入部分"""
        parts = [multimodal_input.text]

        if multimodal_input.image_bytes:
            try:
                img = PIL.Image.open(io.BytesIO(multimodal_input.image_bytes))
                parts.append(img)
            except PIL.UnidentifiedImageError as e:
                logger.warning(f"图片格式无法识别: {e}")
                raise

        if multimodal_input.audio_bytes:
            parts.append(types.Part.from_bytes(
                data=multimodal_input.audio_bytes,
                mime_type=multimodal_input.audio_mime
            ))

        return parts

    def chat(
        self,
        messages: List[ChatMessage],
        system_instruction: str,
        multimodal_input: Optional[MultimodalInput] = None,
        tools: Optional[List[Callable]] = None,
        use_smart_model: bool = False,
        max_tool_calls: int = 10
    ) -> ChatResponse:
        """发送消息并获取响应"""
        try:
            model_name = self.get_model_name(use_smart_model)

            # 转换历史记录格式
            history = self._convert_history_to_gemini_format(messages)

            # 创建配置
            config_kwargs = {
                "system_instruction": system_instruction,
                "temperature": 0.7,
            }

            # 只有当有工具时才添加工具配置
            if tools:
                config_kwargs["tools"] = tools
                config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                    disable=False,
                    maximum_remote_calls=max_tool_calls
                )

            # 创建 chat session
            chat_session = self.client.chats.create(
                model=model_name,
                config=types.GenerateContentConfig(**config_kwargs),
                history=history
            )

            # 构建输入
            if multimodal_input:
                parts = self._build_multimodal_parts(multimodal_input)
                message_input = parts[0] if len(parts) == 1 else parts
            else:
                message_input = ""  # 空消息（不应该发生）

            # 发送消息
            response = chat_session.send_message(message_input)

            # 提取响应文本
            response_text = ""
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text and not getattr(part, 'thought', False):
                        response_text += part.text

            if not response_text.strip():
                response_text = "抱歉，我暂时无法回应。"

            return ChatResponse(
                text=response_text,
                success=True,
                raw_response=response
            )

        except genai.errors.APIError as e:
            error_msg = e.message if hasattr(e, 'message') else str(e)
            logger.error(f"Gemini API 错误: {error_msg}")
            return ChatResponse(
                text=f"API 调用失败，请稍后重试。错误: {error_msg}",
                success=False,
                error_message=error_msg
            )
        except PIL.UnidentifiedImageError as e:
            logger.warning(f"图片格式无法识别: {e}")
            return ChatResponse(
                text="抱歉，无法识别这张图片的格式。",
                success=False,
                error_message=str(e)
            )
        except Exception as e:
            logger.exception(f"Gemini Provider 异常: {e}")
            return ChatResponse(
                text=f"处理请求时发生错误: {type(e).__name__}",
                success=False,
                error_message=str(e)
            )
