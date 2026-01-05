# core/llm/gemini.py
"""
Gemini LLM Provider 实现
"""

import logging
import inspect
import io
import json
import time
from typing import List, Optional, Callable

import PIL.Image
from google import genai
from google.genai import types

import config
from utils.logging_setup import get_request_id
from utils.user_context import get_current_user_id
from core.llm.base import (
    LLMProvider,
    ChatMessage,
    ChatResponse,
    MultimodalInput,
    MessageRole
)

logger = logging.getLogger("Amaya.LLM.Gemini")
payload_logger = logging.getLogger("Amaya.LLM.Payload")


def _truncate_for_log(text: str, max_length: int = 300) -> str:
    """限制日志中的文本长度，避免打印过长或包含敏感内容。"""
    if not text:
        return ""
    clean = text.replace("\n", " ")
    return clean[:max_length] + ("..." if len(clean) > max_length else "")


def _serialize_history(messages: List[ChatMessage]) -> list[dict]:
    """序列化历史消息，供完整日志或调试使用。"""
    result = []
    for msg in messages:
        result.append({
            "role": msg.role.value,
            "text": msg.text,
            "timestamp": msg.timestamp
        })
    return result


def _build_function_declaration(client: genai.Client, func: Callable) -> types.FunctionDeclaration:
    from_callable = types.FunctionDeclaration.from_callable
    try:
        signature = inspect.signature(from_callable)
    except (TypeError, ValueError):
        return from_callable(func)

    if "client" in signature.parameters:
        api_client = getattr(client, "_api_client", None)
        if api_client is None:
            raise RuntimeError("Gemini client missing _api_client for tool declaration.")
        return from_callable(client=api_client, callable=func)

    if "callable" in signature.parameters:
        return from_callable(callable=func)

    return from_callable(func)


def _normalize_tool_args(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _normalize_tool_args(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_tool_args(v) for v in value]
    return value


def _extract_function_calls(response: types.GenerateContentResponse) -> list[types.FunctionCall]:
    calls: list[types.FunctionCall] = []
    if not response.candidates or not response.candidates[0].content:
        return calls
    parts = response.candidates[0].content.parts or []
    for part in parts:
        if part.function_call:
            calls.append(part.function_call)
    return calls


def _get_response_text(response: types.GenerateContentResponse) -> str:
    if not response.candidates or not response.candidates[0].content:
        return ""
    parts = response.candidates[0].content.parts or []
    text = ""
    for part in parts:
        if hasattr(part, "text") and part.text and not getattr(part, 'thought', False):
            text += part.text
    return text


def _build_tool_summary(tool_trace: list[dict]) -> str:
    """根据工具调用记录生成简洁的摘要回复"""
    if not tool_trace:
        return ""
    successful = [t for t in tool_trace if t.get("success")]
    if not successful:
        return ""

    summaries = []
    for call in successful:
        name = call.get("name", "")
        output = call.get("output", "")
        # 根据工具类型生成友好摘要
        if name == "schedule_reminder":
            # 从输出中提取时间信息
            if "计划" in output and "执行" in output:
                summaries.append(f"✓ {output.split('：', 1)[-1].strip() if '：' in output else '提醒已设置'}")
            else:
                summaries.append("✓ 提醒已设置")
        elif name == "save_memory":
            summaries.append(f"✓ 已保存到文件")
        elif name == "add_schedule_item":
            summaries.append("✓ 日程已添加")
        elif name.startswith("update_") or name.startswith("move_"):
            summaries.append("✓ 日程已更新")
        elif name.startswith("remove_") or name.startswith("clear_"):
            summaries.append("✓ 已删除")
        else:
            # 通用处理
            summaries.append(f"✓ {name} 完成")

    return "\n".join(summaries) if summaries else ""


def _execute_tool_call(name: str, args: dict, tool_map: dict[str, Callable]) -> tuple[bool, str]:
    if not name or name not in tool_map:
        return False, f"Error: Unknown function {name}"
    try:
        result = tool_map[name](**args)
        return True, str(result)
    except Exception as e:
        logger.error(f"Gemini tool execution failed {name}: {e}")
        return False, f"Error executing {name}: {str(e)}"


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
        log_full_payload = config.LOG_LLM_PAYLOADS == "full"
        request_id = get_request_id()
        user_id = get_current_user_id()
        model_name = self.get_model_name(use_smart_model)
        request_payload = None
        if log_full_payload:
            request_payload = {
                "system_instruction": system_instruction,
                "history": _serialize_history(messages),
                "input_text": multimodal_input.text if multimodal_input else "",
                "has_image": bool(multimodal_input.image_bytes) if multimodal_input else False,
                "has_audio": bool(multimodal_input.audio_bytes) if multimodal_input else False,
                "image_bytes_len": len(multimodal_input.image_bytes) if multimodal_input else 0,
                "audio_bytes_len": len(multimodal_input.audio_bytes) if multimodal_input else 0,
                "tools": [func.__name__ for func in tools] if tools else [],
            }

        tool_call_trace: list[dict] = []

        def _emit_full_payload(success: bool, response_text: str = "", error_message: str = "") -> None:
            if not log_full_payload:
                return
            payload = {
                "timestamp": time.time(),
                "request_id": request_id,
                "user_id": user_id,
                "provider": self.provider_name,
                "model": model_name,
                "use_smart": use_smart_model,
                "request": request_payload,
                "tool_calls": tool_call_trace,
                "response": {
                    "success": success,
                    "text": response_text,
                    "error_message": error_message,
                }
            }
            payload_logger.info(json.dumps(payload, ensure_ascii=False))

        try:
            start_time = time.time()

            # 转换历史记录格式
            history = self._convert_history_to_gemini_format(messages)

            # 创建配置
            config_kwargs = {
                "system_instruction": system_instruction,
                "temperature": config.GEMINI_TEMPERATURE,
            }

            tool_map: dict[str, Callable] = {}
            if tools:
                tool_map = {func.__name__: func for func in tools}
                tool_declarations = []
                for func in tools:
                    try:
                        tool_declarations.append(_build_function_declaration(self.client, func))
                    except Exception as e:
                        logger.warning("Gemini tool declaration failed: %s", e)
                if tool_declarations:
                    config_kwargs["tools"] = [types.Tool(function_declarations=tool_declarations)]
                    config_kwargs["tool_config"] = types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode=types.FunctionCallingConfigMode.AUTO
                        )
                    )

            preview_text = _truncate_for_log(multimodal_input.text if multimodal_input else "")
            logger.info(
                "Gemini chat 请求: model=%s use_smart=%s history=%s tools=%s has_image=%s has_audio=%s input_preview=\"%s\"",
                model_name,
                use_smart_model,
                len(messages),
                [func.__name__ for func in tools] if tools else [],
                bool(multimodal_input.image_bytes) if multimodal_input else False,
                bool(multimodal_input.audio_bytes) if multimodal_input else False,
                preview_text,
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

            response = chat_session.send_message(message_input)

            tool_call_count = 0
            response_text = ""
            while tool_call_count < max_tool_calls:
                function_calls = _extract_function_calls(response)
                if not function_calls:
                    response_text = _get_response_text(response)
                    break

                response_parts: list[types.Part] = []
                for call in function_calls:
                    if tool_call_count >= max_tool_calls:
                        break
                    name = call.name or ""
                    args = call.args or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    if isinstance(args, dict):
                        args = _normalize_tool_args(args)
                    else:
                        args = {}
                    success, result = _execute_tool_call(name, args, tool_map)
                    tool_call_trace.append({
                        "name": name,
                        "arguments": args,
                        "output": result,
                        "success": success
                    })
                    response_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=call.id,
                                name=name,
                                response={"result": result} if success else {"error": result}
                            )
                        )
                    )
                    tool_call_count += 1
                    logger.info(
                        "Gemini tool call #%s name=%s success=%s output_preview=\"%s\"",
                        tool_call_count,
                        name,
                        success,
                        _truncate_for_log(result, 200),
                    )

                if not response_parts:
                    response_text = _get_response_text(response)
                    break

                try:
                    response = chat_session.send_message(response_parts)
                except genai.errors.APIError as tool_response_error:
                    # 工具调用后 Gemini 返回空响应（thinking model 可能只有 thought 无文本）
                    error_str = str(tool_response_error)
                    if "empty response" in error_str or "no meaningful content" in error_str:
                        logger.warning(
                            "Gemini 工具响应后返回空内容，使用工具摘要作为回复: %s",
                            _truncate_for_log(error_str, 100)
                        )
                        tool_summary = _build_tool_summary(tool_call_trace)
                        if tool_summary:
                            response_text = tool_summary
                            break
                    # 其他 API 错误继续抛出
                    raise

            if not response_text:
                response_text = _get_response_text(response)

            if not response_text.strip():
                # 如果仍然为空但有成功的工具调用，使用工具摘要
                tool_summary = _build_tool_summary(tool_call_trace)
                if tool_summary:
                    response_text = tool_summary
                else:
                    response_text = "抱歉，我暂时无法回应。"

            elapsed = time.time() - start_time
            logger.info(
                "Gemini chat 完成 model=%s use_smart=%s elapsed_sec=%.3f response_preview=\"%s\"",
                model_name,
                use_smart_model,
                elapsed,
                _truncate_for_log(response_text, 400),
            )

            _emit_full_payload(True, response_text=response_text)

            return ChatResponse(
                text=response_text,
                success=True,
                raw_response=response
            )

        except genai.errors.APIError as e:
            error_msg = e.message if hasattr(e, 'message') else str(e)
            logger.error(f"Gemini API 错误: {error_msg}")
            _emit_full_payload(False, error_message=error_msg)
            return ChatResponse(
                text=f"API 调用失败，请稍后重试。错误: {error_msg}",
                success=False,
                error_message=error_msg
            )
        except PIL.UnidentifiedImageError as e:
            logger.warning(f"图片格式无法识别: {e}")
            _emit_full_payload(False, error_message=str(e))
            return ChatResponse(
                text="抱歉，无法识别这张图片的格式。",
                success=False,
                error_message=str(e)
            )
        except Exception as e:
            logger.exception(f"Gemini Provider 异常: {e}")
            _emit_full_payload(False, error_message=str(e))
            return ChatResponse(
                text=f"处理请求时发生错误: {type(e).__name__}",
                success=False,
                error_message=str(e)
            )
