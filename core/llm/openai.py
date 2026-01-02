# core/llm/openai.py
"""
OpenAI LLM Provider 实现
仅使用 Responses API（弃用 Chat Completions）
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
    elif hasattr(py_type, "__origin__"):
        origin = py_type.__origin__
        if origin is list:
            return {"type": "array"}
        elif str(origin) == "typing.Union":
            args = py_type.__args__
            non_none_args = [a for a in args if a is not type(None)]
            if non_none_args:
                return _python_type_to_json_schema(non_none_args[0])
    return {"type": "string"}


def _convert_function_to_openai_tool(func: Callable) -> dict:
    """将 Python 函数转换为 OpenAI Function Calling 格式"""
    import inspect

    sig = inspect.signature(func)
    type_hints = get_type_hints(func) if hasattr(func, '__annotations__') else {}

    doc = func.__doc__ or ""
    lines = doc.strip().split('\n')
    description = lines[0].strip() if lines else func.__name__

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

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ('self', 'cls'):
            continue

        param_type = type_hints.get(param_name, str)
        param_schema = _python_type_to_json_schema(param_type)
        param_schema["description"] = param_descriptions.get(param_name, "")
        properties[param_name] = param_schema

        if param.default is inspect.Parameter.empty:
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
    """OpenAI Responses API 提供者"""

    def __init__(
        self,
        api_key: str,
        smart_model: str = "gpt-4o",
        fast_model: str = "gpt-4o-mini",
        api_base: Optional[str] = None,
        reasoning_effort: Optional[str] = None
    ):
        super().__init__(smart_model, fast_model)

        client_kwargs = {"api_key": api_key}
        if api_base:
            client_kwargs["base_url"] = api_base

        self.client = OpenAI(**client_kwargs)
        self._tools_map: dict[str, Callable] = {}

        # reasoning 配置（仅 smart 模式生效）
        allowed_effort = {"low", "medium", "high"}
        if reasoning_effort:
            normalized = reasoning_effort.lower()
            self.reasoning_effort = normalized if normalized in allowed_effort else None
            if not self.reasoning_effort:
                logger.warning(f"无效的 reasoning_effort: {reasoning_effort}, 将忽略")
        else:
            self.reasoning_effort = None

        logger.info(f"OpenAI Provider 初始化完成，Smart: {smart_model}, Fast: {fast_model}")
        if api_base:
            logger.info(f"使用自定义 Base URL: {api_base}")
        logger.info("使用 Responses API")

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

        if system_instruction:
            formatted.append({
                "role": "system",
                "content": system_instruction
            })

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

        if multimodal_input.text:
            content.append({
                "type": "text",
                "text": multimodal_input.text
            })

        if multimodal_input.image_bytes:
            image_b64 = base64.b64encode(multimodal_input.image_bytes).decode('utf-8')
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}"
                }
            })

        if multimodal_input.audio_bytes:
            logger.warning("OpenAI Provider 暂不支持直接音频输入，音频将被忽略")

        return content

    def _execute_tool_call(self, name: str, arguments: dict) -> str:
        """执行工具调用并返回结果"""
        if name not in self._tools_map:
            return f"Error: Unknown function {name}"

        try:
            func = self._tools_map[name]
            result = func(**arguments)
            return str(result)
        except Exception as e:
            logger.error(f"工具执行失败 {name}: {e}")
            return f"Error executing {name}: {str(e)}"

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
        使用 Responses API 发送消息并获取响应
        - smart 模式：启用 reasoning（如果配置了 reasoning_effort）
        - fast 模式：不启用 reasoning
        - 两种模式都支持 tools
        """
        try:
            model_name = self.get_model_name(use_smart_model)

            # 转换历史记录格式
            openai_messages = self._convert_history_to_openai_format(messages, system_instruction)

            # 添加当前用户输入
            if multimodal_input:
                if multimodal_input.image_bytes:
                    content = self._build_multimodal_content(multimodal_input)
                    openai_messages.append({
                        "role": "user",
                        "content": content
                    })
                else:
                    openai_messages.append({
                        "role": "user",
                        "content": multimodal_input.text
                    })

            # 构建请求参数
            req_kwargs = {
                "model": model_name,
                "input": openai_messages,
            }

            # 仅在 smart 模式下启用 reasoning
            if use_smart_model and self.reasoning_effort:
                req_kwargs["reasoning"] = {"effort": self.reasoning_effort}

            # 添加工具定义
            if tools:
                self._tools_map = {func.__name__: func for func in tools}
                req_kwargs["tools"] = [_convert_function_to_openai_tool(func) for func in tools]

            tool_call_count = 0
            conversation_input = openai_messages.copy()
            response = None
            final_text = ""

            while tool_call_count < max_tool_calls:
                req_kwargs["input"] = conversation_input
                response = self.client.responses.create(**req_kwargs)

                # 检查 output
                output = getattr(response, "output", [])
                if not output:
                    final_text = getattr(response, "output_text", "") or ""
                    break

                # 收集所有 tool_call 和最终文本
                tool_calls_found = []
                final_text = ""

                for item in output:
                    item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)

                    if item_type == "function_call":
                        if isinstance(item, dict):
                            call_id = item.get("call_id", item.get("id", ""))
                            name = item.get("name", "")
                            arguments = item.get("arguments", {})
                        else:
                            call_id = getattr(item, "call_id", getattr(item, "id", ""))
                            name = getattr(item, "name", "")
                            arguments = getattr(item, "arguments", {})

                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except json.JSONDecodeError:
                                arguments = {}

                        tool_calls_found.append({
                            "call_id": call_id,
                            "name": name,
                            "arguments": arguments
                        })

                    elif item_type == "message":
                        if isinstance(item, dict):
                            content = item.get("content", [])
                        else:
                            content = getattr(item, "content", [])

                        for c in (content if isinstance(content, list) else [content]):
                            if isinstance(c, dict) and c.get("type") == "output_text":
                                final_text += c.get("text", "")
                            elif isinstance(c, str):
                                final_text += c

                # 如果没有工具调用，跳出循环
                if not tool_calls_found:
                    final_text = getattr(response, "output_text", "") or final_text
                    break

                # 执行工具调用并添加结果到对话
                for tc in tool_calls_found:
                    conversation_input.append({
                        "type": "function_call",
                        "call_id": tc["call_id"],
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"], ensure_ascii=False) if isinstance(tc["arguments"], dict) else tc["arguments"]
                    })

                    result = self._execute_tool_call(tc["name"], tc["arguments"])

                    conversation_input.append({
                        "type": "function_call_output",
                        "call_id": tc["call_id"],
                        "output": result
                    })

                    tool_call_count += 1
                    logger.debug(f"工具调用 [{tool_call_count}]: {tc['name']}")

            # 提取最终响应
            response_text = final_text or getattr(response, "output_text", "") or ""

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
