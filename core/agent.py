# core/agent.py
"""
Amaya Brain - 核心 Agent 逻辑
使用 LLM 抽象层，支持多种 LLM 后端
"""

import time
import logging
from datetime import datetime

import config
from core.llm import create_llm_provider, ChatMessage, MultimodalInput
from core.tools import tools_registry
from utils.storage import get_global_context_string, load_json, save_json

logger = logging.getLogger("Amaya.Agent")


class AmayaBrain:
    def __init__(self):
        # 1. 根据配置创建 LLM 提供者
        self._init_llm_provider()

        # 2. 短期记忆缓存
        # 结构: [{"role": "user/model", "text": "...", "timestamp": 123456789}]
        self.short_term_memory = self._load_short_term_memory()

        # 核心人设
        self.system_instruction = config.CHAT_SYSTEM_PROMPT
        self.maintenance_instruction = config.MAINTENANCE_SYSTEM_PROMPT

    def _init_llm_provider(self):
        """根据配置初始化 LLM 提供者"""
        provider_type = config.LLM_PROVIDER

        if provider_type == "gemini":
            self.llm = create_llm_provider(
                provider_type="gemini",
                api_key=config.GEMINI_API_KEY,
                smart_model=config.GEMINI_SMART_MODEL,
                fast_model=config.GEMINI_FAST_MODEL,
                api_base=config.GEMINI_API_BASE or None
            )
        elif provider_type == "openai":
            self.llm = create_llm_provider(
                provider_type="openai",
                api_key=config.OPENAI_API_KEY,
                smart_model=config.OPENAI_SMART_MODEL,
                fast_model=config.OPENAI_FAST_MODEL,
                api_base=config.OPENAI_API_BASE or None
            )
        else:
            raise ValueError(f"不支持的 LLM Provider: {provider_type}")

        logger.info(f"LLM Provider 初始化: {self.llm.provider_name}")

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

    def _get_cleaned_history(self) -> list[ChatMessage]:
        """剔除过期的历史记录，返回 ChatMessage 列表"""
        cutoff = time.time() - config.SHORT_TERM_MEMORY_TTL
        self.short_term_memory = [m for m in self.short_term_memory if m.get("timestamp", 0) > cutoff]

        # 转换为统一的 ChatMessage 格式
        messages = []
        for m in self.short_term_memory:
            messages.append(ChatMessage.from_dict(m))
        return messages

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

            # 2. 构造 Prompt，把记忆强行塞进上下文
            full_input = f"""
[WORLD CONTEXT]
{global_context}

[WORLD BACKGROUD]
{self.get_world_background()}

[USER INPUT]
{user_text}
"""

            # 3. 构造多模态输入
            multimodal_input = MultimodalInput(
                text=full_input,
                image_bytes=image_bytes,
                audio_bytes=audio_bytes,
                audio_mime=audio_mime
            )

            # 4. 调用 LLM
            response = self.llm.chat(
                messages=history,
                system_instruction=self.system_instruction,
                multimodal_input=multimodal_input,
                tools=tools_registry,
                use_smart_model=use_smart,
                max_tool_calls=10
            )

            response_text = response.text

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
            multimodal_input = MultimodalInput(text=maintenance_prompt)

            response = self.llm.chat(
                messages=[],  # 无历史记录
                system_instruction=self.system_instruction + self.maintenance_instruction,
                multimodal_input=multimodal_input,
                tools=tools_registry,
                use_smart_model=True,
                max_tool_calls=10
            )

            response_text = response.text
            if not response_text:
                response_text = "System clean."

            return f"整理报告: {response_text}"

        except Exception as e:
            logger.exception(f"整理任务异常: {e}")
            return f"整理失败: {type(e).__name__}: {str(e)}"


amaya = AmayaBrain()
