# core/llm/openai.py
"""
OpenAI (ChatGPT) LLM Provider 实现
支持第三方 BaseURL
"""

import base64
import json
import logging
from typing import List, Optional, Callable, Any, get_type_hints

from openai import OpenAI
from openai import APIError, APIConnectionError, RateLimitError

from core.llm.base import (
    LLMProvider,
    ChatMessage,
    ChatResponse,
    MultimodalInput,
    MessageRole
)

logger = logging.getLogger("Amaya.LLM.OpenAI")


def _python_type_to_json_schema(py_type: Any) -> dict:
    """将 Python 类型转换为 JSON Schema 类型"""
    if py_type is str:
        return {"type": "string"}
    elif py_type is int:
        return {"type": "integer"}
    elif py_type is float:
        return {"type": "number"}
    elif py_type is bool:
        return {"type": "boolean"}
    elif py_type is list:
        return {"type": "array"}
    elif py_type is dict:
        return {"type": "object"}
    elif hasattr(py_type, "__origin__"):  # 处理 Optional, List 等泛型
        origin = py_type.__origin__
        if origin is list:
            return {"type": "array"}
        # Optional[X] 实际上是 Union[X, None]
        elif str(origin) == "typing.Union":
            args = py_type.__args__
            # 过滤掉 NoneType
            non_none_args = [a for a in args if a is not type(None)]
            if non_none_args:
                return _python_type_to_json_schema(non_none_args[0])
    return {"type": "string"}  # 默认返回 string


def _convert_function_to_openai_tool(func: Callable) -> dict:
    """
    将 Python 函数转换为 OpenAI Function Calling 格式
    依赖函数的 docstring 和类型注解
    """
    import inspect

    # 获取函数签名
    sig = inspect.signature(func)
    type_hints = get_type_hints(func) if hasattr(func, '__annotations__') else {}

    # 解析 docstring
    doc = func.__doc__ or ""
    lines = doc.strip().split('\n')

    # 提取描述（第一行）
    description = lines[0].strip() if lines else func.__name__

    # 解析参数描述
    param_descriptions = {}
    in_args = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Args:"):
            in_args = True
            continue
        if in_args:
            if stripped.startswith("Returns:") or stripped.startswith("Raises:"):
                break
            if ":" in stripped:
                param_name, param_desc = stripped.split(":", 1)
                param_descriptions[param_name.strip()] = param_desc.strip()

    # 构建参数 schema
    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ('self', 'cls'):
            continue

        param_type = type_hints.get(param_name, str)
        param_schema = _python_type_to_json_schema(param_type)
        param_schema["description"] = param_descriptions.get(param_name, "")

        properties[param_name] = param_schema

        # 如果没有默认值，则为必需参数
        if param.default is inspect.Parameter.empty:
            # 检查是否是 Optional 类型
            if hasattr(param_type, "__origin__") and str(param_type.__origin__) == "typing.Union":
                args = param_type.__args__
                if type(None) not in args:
                    required.append(param_name)
            else:
                required.append(param_name)

    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
    }


class OpenAIProvider(LLMProvider):
    """OpenAI (ChatGPT) API 提供者"""

    def __init__(
        self,
        api_key: str,
        smart_model: str = "gpt-4o",
        fast_model: str = "gpt-4o-mini",
        api_base: Optional[str] = None
    ):
        super().__init__(smart_model, fast_model)

        # 初始化客户端
        client_kwargs = {"api_key": api_key}
        if api_base:
            client_kwargs["base_url"] = api_base

        self.client = OpenAI(**client_kwargs)
        self._tools_map: dict[str, Callable] = {}  # 工具名称 -> 函数映射

        logger.info(f"OpenAI Provider 初始化完成，Smart: {smart_model}, Fast: {fast_model}")
        if api_base:
            logger.info(f"使用自定义 Base URL: {api_base}")

    @property
    def provider_name(self) -> str:
        return "openai"

    def get_model_name(self, use_smart: bool = False) -> str:
        return self.smart_model if use_smart else self.fast_model

    def _convert_history_to_openai_format(
        self,
        messages: List[ChatMessage],
        system_instruction: str
    ) -> List[dict]:
        """将统一消息格式转换为 OpenAI 格式"""
        formatted = []

        # 添加系统消息
        if system_instruction:
            formatted.append({
                "role": "system",
                "content": system_instruction
            })

        # 转换历史消息
        for msg in messages:
            role = "user" if msg.role == MessageRole.USER else "assistant"
            formatted.append({
                "role": role,
                "content": msg.text
            })

        return formatted

    def _build_multimodal_content(self, multimodal_input: MultimodalInput) -> list:
        """构建多模态消息内容"""
        content = []

        # 添加文本
        if multimodal_input.text:
            content.append({
                "type": "text",
                "text": multimodal_input.text
            })

        # 添加图片
        if multimodal_input.image_bytes:
            # OpenAI 需要 base64 编码的图片
            image_b64 = base64.b64encode(multimodal_input.image_bytes).decode('utf-8')
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}"
                }
            })

        # 注意：OpenAI 的音频处理方式不同，这里简化处理
        if multimodal_input.audio_bytes:
            logger.warning("OpenAI Provider 暂不支持直接音频输入，音频将被忽略")

        return content

    def _execute_tool_call(self, tool_call: Any) -> str:
        """执行工具调用并返回结果"""
        func_name = tool_call.function.name
        func_args = json.loads(tool_call.function.arguments)

        if func_name not in self._tools_map:
            return f"Error: Unknown function {func_name}"

        try:
            func = self._tools_map[func_name]
            result = func(**func_args)
            return str(result)
        except Exception as e:
            logger.error(f"工具执行失败 {func_name}: {e}")
            return f"Error executing {func_name}: {str(e)}"

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
            openai_messages = self._convert_history_to_openai_format(messages, system_instruction)

            # 添加当前用户输入
            if multimodal_input:
                if multimodal_input.image_bytes:
                    # 多模态消息
                    content = self._build_multimodal_content(multimodal_input)
                    openai_messages.append({
                        "role": "user",
                        "content": content
                    })
                else:
                    # 纯文本消息
                    openai_messages.append({
                        "role": "user",
                        "content": multimodal_input.text
                    })

            # 转换工具格式
            openai_tools = None
            if tools:
                self._tools_map = {func.__name__: func for func in tools}
                openai_tools = [_convert_function_to_openai_tool(func) for func in tools]

            # 准备请求参数
            request_kwargs = {
                "model": model_name,
                "messages": openai_messages,
                "temperature": 0.7,
            }

            if openai_tools:
                request_kwargs["tools"] = openai_tools
                request_kwargs["tool_choice"] = "auto"

            # 发送请求，处理工具调用循环
            tool_call_count = 0

            while tool_call_count < max_tool_calls:
                response = self.client.chat.completions.create(**request_kwargs)

                assistant_message = response.choices[0].message

                # 检查是否有工具调用
                if assistant_message.tool_calls:
                    # 添加助手消息到历史
                    openai_messages.append({
                        "role": "assistant",
                        "content": assistant_message.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in assistant_message.tool_calls
                        ]
                    })

                    # 执行每个工具调用
                    for tool_call in assistant_message.tool_calls:
                        result = self._execute_tool_call(tool_call)
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })
                        tool_call_count += 1
                        logger.debug(f"工具调用 [{tool_call_count}]: {tool_call.function.name}")

                    # 更新请求参数的消息
                    request_kwargs["messages"] = openai_messages
                else:
                    # 没有工具调用，返回结果
                    break

            # 提取最终响应文本
            response_text = assistant_message.content or ""

            if not response_text.strip():
                response_text = "抱歉，我暂时无法回应。"

            return ChatResponse(
                text=response_text,
                success=True,
                raw_response=response
            )

        except APIConnectionError as e:
            logger.error(f"OpenAI API 连接错误: {e}")
            return ChatResponse(
                text="API 连接失败，请检查网络或 Base URL 配置。",
                success=False,
                error_message=str(e)
            )
        except RateLimitError as e:
            logger.error(f"OpenAI API 限流: {e}")
            return ChatResponse(
                text="API 调用频率过高，请稍后重试。",
                success=False,
                error_message=str(e)
            )
        except APIError as e:
            logger.error(f"OpenAI API 错误: {e}")
            return ChatResponse(
                text=f"API 调用失败，请稍后重试。错误: {str(e)}",
                success=False,
                error_message=str(e)
            )
        except Exception as e:
            logger.exception(f"OpenAI Provider 异常: {e}")
            return ChatResponse(
                text=f"处理请求时发生错误: {type(e).__name__}",
                success=False,
                error_message=str(e)
            )
