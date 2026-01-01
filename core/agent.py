# core/agent.py
import time
import logging
import PIL.Image
import io
from google import genai
from google.genai import types
import config
from core.tools import tools_registry
from utils.storage import get_global_context_string, load_json, save_json
from datetime import datetime

logger = logging.getLogger("Amaya.Agent")


class AmayaBrain:
    def __init__(self):
        # 1. 配置 HTTP 选项 (代理)
        http_options = None
        if config.GEMINI_API_BASE:
            http_options = types.HttpOptions(
                base_url=config.GEMINI_API_BASE,
                api_version="v1beta"
            )

        # 2. 初始化客户端
        self.client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=http_options
        )

        self.smart_model = config.SMART_MODEL
        self.fast_model = config.FAST_MODEL

        # 3. 短期记忆缓存
        # 结构: [{"role": "user/model", "text": "...", "timestamp": 123456789}]
        self.short_term_memory = self._load_short_term_memory()

        # 核心人设
        self.system_instruction = config.CHAT_SYSTEM_PROMPT
        self.maintenance_instruction = config.MAINTENANCE_SYSTEM_PROMPT

    def _load_short_term_memory(self) -> list:
        """从持久化存储加载短期记忆"""
        try:
            memory = load_json("short_term_memory", default=[])
            if not isinstance(memory, list):
                logger.warning("短期记忆格式异常，已重置")
                return []
            # 过滤掉过期的记忆
            cutoff = time.time() - config.SHORT_TERM_MEMORY_TTL
            valid_memory = [m for m in memory if m.get("timestamp", 0) > cutoff]
            logger.info(f"已加载 {len(valid_memory)} 条短期记忆")
            return valid_memory
        except Exception as e:
            logger.error(f"加载短期记忆失败: {e}")
            return []

    def _save_short_term_memory(self):
        """持久化保存短期记忆"""
        try:
            if save_json("short_term_memory", self.short_term_memory):
                logger.debug(f"已保存 {len(self.short_term_memory)} 条短期记忆")
            else:
                logger.warning("短期记忆保存失败")
        except Exception as e:
            logger.error(f"保存短期记忆异常: {e}")

    def shutdown(self):
        """优雅关闭，保存状态"""
        logger.info("正在保存 Amaya 状态...")
        self._save_short_term_memory()
        logger.info("Amaya 状态已保存")

    def _get_cleaned_history(self):
        """剔除过期的历史记录"""
        cutoff = time.time() - config.SHORT_TERM_MEMORY_TTL
        self.short_term_memory = [m for m in self.short_term_memory if m.get("timestamp", 0) > cutoff]

        # 转换为 Gemini 接受的 history 格式 (不带时间戳)
        formatted_history = []
        for m in self.short_term_memory:
            formatted_history.append({"role": m["role"], "parts": [{"text": m["text"]}]})
        return formatted_history


    def _create_chat(self, use_smart_model=False, system_instruction=None, history=None, maximum_remote_calls=10):
        """根据任务难度选择模型"""
        model_name = self.smart_model if use_smart_model else self.fast_model

        return self.client.chats.create(
            model=model_name,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction or self.system_instruction,
                temperature=0.7,
                tools=tools_registry,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=False, maximum_remote_calls=maximum_remote_calls
                )
            ),
            history=history
        )


    def get_world_background(self):
        """
        获取当前时间、日期、最近节假日信息(ToDo)。
        """
        now = datetime.now()
        return f"Current Time: {now.strftime('%Y-%m-%d %A %H:%M')}"


    def chat_sync(self, user_text: str, image_bytes: bytes = b'', audio_bytes: bytes = b'', audio_mime: str = "audio/ogg") -> str:
        """
        同步版本的 chat 方法，用于在线程池中执行。
        这样可以避免阻塞主事件循环，让 typing 指示器正常工作。
        """
        # 动态选择模型
        # 如果涉及规划、反思、大量文件操作，切换到 Smart 模型
        logic_keywords = ["规划", "计划", "安排", "整理", "复盘", "反思", "分析", "schedule", "plan"]
        use_smart = (image_bytes or audio_bytes) or any(k in user_text for k in logic_keywords)

        try:
            # 1. 获取上下文
            global_context = get_global_context_string()

            # 获取并清理短期对话历史
            history = self._get_cleaned_history()

            chat_session = self._create_chat(use_smart_model=use_smart, history=history)

            # 2. 构造 Prompt，把记忆强行塞进上下文
            full_input = f"""
[WORLD CONTEXT]
{global_context}

[WORLD BACKGROUD]
{self.get_world_background()}

[USER INPUT]
{user_text}
"""

            # 构造 Content 对象，支持多模态输入
            parts = [full_input]  # 文本可以直接作为字符串
            if image_bytes:
                # 使用 PIL 处理字节流
                img = PIL.Image.open(io.BytesIO(image_bytes))
                parts.append(img)  # PIL.Image 可以直接传入
            if audio_bytes:
                parts.append(types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime or "audio/ogg"))

            # 直接传递 parts 列表（单个元素时传元素本身）
            message_input = parts[0] if len(parts) == 1 else parts
            response = chat_session.send_message(message_input)

            response_text = ""
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text and not getattr(part, 'thought', False):
                        response_text += part.text

            # 确保不返回空字符串
            if not response_text.strip():
                response_text = "抱歉，我暂时无法回应。"

            # 更新短期记忆库
            current_time = time.time()
            self.short_term_memory.append({"role": "user", "text": user_text, "timestamp": current_time})
            self.short_term_memory.append({"role": "model", "text": response_text, "timestamp": current_time})

            # 保存短期记忆
            self._save_short_term_memory()

            return response_text
        except genai.errors.APIError as e:
            logger.error(f"Gemini API 错误: {e}")
            return f"API 调用失败，请稍后重试。错误: {e.message if hasattr(e, 'message') else str(e)}"
        except PIL.UnidentifiedImageError as e:
            logger.warning(f"图片格式无法识别: {e}")
            return "抱歉，无法识别这张图片的格式。"
        except Exception as e:
            logger.exception(f"Amaya 核心逻辑异常: {e}")
            return f"处理请求时发生错误: {type(e).__name__}"

    async def chat(self, user_text: str, image_bytes: bytes = b'', audio_bytes: bytes = b'', audio_mime: str = "audio/ogg") -> str:
        """
        异步版本的 chat 方法，内部调用 chat_sync。
        保留此方法以保持向后兼容性（如 tidying_up 等内部调用）。
        """
        import asyncio
        return await asyncio.to_thread(
            self.chat_sync, user_text, image_bytes, audio_bytes, audio_mime
        )


    async def tidying_up(self):
        """
        [自主整理模式]
        这是你的"潜意识整理时间"。
        不接收用户输入，而是自我反思文件结构。
        """
        try:
            logger.info("Amaya 正在进行自主整理...")
            context = get_global_context_string()
            maintenance_prompt = f"""
[System Maintenance Mode]
Context:
{context}
"""
            # 使用独立的 chat session（无历史记录）避免上下文污染
            chat_session = self._create_chat(use_smart_model=True, system_instruction=self.system_instruction + self.maintenance_system_prompt, history=[])
            response = chat_session.send_message(maintenance_prompt)

            response_text = ""
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text and not getattr(part, 'thought', False):
                        response_text += part.text

            if not response_text:
                response_text = "System clean."

            return f"整理报告: {response_text}"
        except genai.errors.APIError as e:
            error_msg = e.message if hasattr(e, 'message') else str(e)
            logger.error(f"整理任务 API 错误: {error_msg}")
            return f"整理任务 API 调用失败: {error_msg}"
        except Exception as e:
            logger.exception(f"整理任务异常: {e}")
            return f"整理失败: {type(e).__name__}: {str(e)}"


amaya = AmayaBrain()
