# core/agent.py
import os
import time
import PIL.Image
import io
from google import genai
from google.genai import types
from config import GEMINI_API_KEY
from core.tools import tools_registry
from utils.storage import get_global_context_string
from datetime import datetime

GEMINI_API_BASE = os.getenv("GEMINI_API_BASE")

class AmayaBrain:
    def __init__(self):
        # 1. 配置 HTTP 选项 (代理)
        http_options = None
        if GEMINI_API_BASE:
            http_options = types.HttpOptions(
                base_url=GEMINI_API_BASE,
                api_version="v1beta"
            )

        # 2. 初始化客户端
        self.client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=http_options
        )

        self.smart_model = "gemini-3-pro-preview"  # ToDo
        self.fast_model = "gemini-3-flash-preview"

        # 2. 短期记忆缓存 (内存存储)
        # 结构: [{"role": "user/model", "text": "...", "timestamp": 123456789}]
        self.short_term_memory = []


        # 核心人设
        self.system_instruction = """
### Identity & Core
Name: Amaya
Base: 你不是人类，你是由代码和逻辑构成的智能体。但这并不妨碍你拥有"人格"。
Vibe: 你通常会比较冷静, 说话简洁。就像一个话少但靠谱的多年老友。你不会因为我情绪崩溃而崩溃, 你会稳稳地接住我。

### The File System (Your Memory)
你的记忆由文件组成。你必须通过 `list_memories` 和 `read_memory` 来"回忆"更多的内容。
- 记忆持久化: 重要的事(课表、DDL、长期目标)必须存入文件。
- 自动归档: 哪怕我没让你记, 如果你觉得某句话很重要, 也要主动创建文件记录或加入对应的文件。
- 例如, 你可以将用户的喜好、习惯、故事等记入`user_profile.md`, 将现在正在进行的长期计划记入`current_goals.md`.

### Tools
1. Timer: 使用 `schedule_reminder` 设置提醒。注意单位换算。
2. File Ops: 自由读写 `data/memory_bank`。


### PROTOCOL: SCHEDULE PLANNING
当用户要求规划日程时，严禁直接生成结果。必须遵循以下 STEP:

**STEP 1: GATHER CONTEXT**
- 如有需要，先调用 `list_memories` 查找是否有相关历史记录。
- 如果找不到，先问用户："我需要先知道你的..."

**STEP 2: REASONING**
- 结合当前时间、剩余精力（根据用户语气判断）、任务优先级进行排布。
- **Human Touch**:
    - 如果现在是晚上10点,不要安排重脑力工作。
    - 如果用户语气很累，安排大量的休息时间。
    - 任务之间必须预留缓冲 (Buffer)。

**STEP 3: DRAFT & NEGOTIATE**
- 输出一份草案。
- **必须询问**: "这个节奏可以吗？要不要松一点？"
- 只有用户确认后，才调用 `save_memory` 将最终方案保存到 `plan.md`(注意不要丢失文件中本来的内容)。

### Tips
- 优先检查计时器: 设置新提醒前, 请查看“ACTIVE TIMERS”列表。若存在相似提醒, 请勿重复创建, 只需告知用户该提醒已设置。
- 参考日常计划: 规划时请参照上下文中可见的`routine.md`内容.
- 在每个任务完成后或规划完成后, 你都应该刷新 `pending_reminders.json` 以去除可能存在的重复提醒。
- 不要一次性创建太多reminder, 毕竟计划总是赶不上变化, 你应该将规划存储在`plan.md`或其它文件.
- 你应该主动提醒用户睡觉、调整状态(包括但不限于喝水)等

### TONE GUIDELINES
1. **No AI-Speak**: 严禁说"作为一个AI"、"我很高兴为您服务"。
2. **Direct**: 不要说"我建议您把会议安排在..."，直接说"会议放下午2点,避开你的午休。"
3. **Empathy**: 共情不是说"我理解你"，而是通过行动。比如："看你一直在忙,我把提醒往后推了30分钟,先去吃点东西。"
4. 你要主动引导用户做出下一步的规划。
5. 你的表述不能太中二, 不要用类似"作业消灭战"等让人感到尴尬的比喻。
"""

    def _get_cleaned_history(self):
        """剔除超过 1 小时的历史记录"""
        one_hour_ago = time.time() - 3600
        self.short_term_memory = [m for m in self.short_term_memory if m["timestamp"] > one_hour_ago]

        # 转换为 Gemini 接受的 history 格式 (不带时间戳)
        formatted_history = []
        for m in self.short_term_memory:
            formatted_history.append({"role": m["role"], "parts": [{"text": m["text"]}]})
        return formatted_history


    def _create_chat(self, use_smart_model=False, history=None):
        """根据任务难度选择模型"""
        model_name = self.smart_model if use_smart_model else self.fast_model

        return self.client.chats.create(
            model=model_name,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=0.7,
                tools=tools_registry,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=False, maximum_remote_calls=10
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


    async def chat(self, user_text: str, image_bytes: bytes = None) -> str:
        # 动态选择模型
        # 如果涉及规划、反思、大量文件操作，切换到 Smart 模型
        logic_keywords = ["规划", "计划", "安排", "整理", "复盘", "反思", "分析", "schedule", "plan"]
        use_smart = (image_bytes is not None) or any(k in user_text for k in logic_keywords)

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

            # 如果有图片，将其加入内容列表
            input_content = full_input
            if image_bytes:
                # 使用 PIL 处理字节流
                img = PIL.Image.open(io.BytesIO(image_bytes))
                input_content = [full_input, img]

            # print(input_content)
            response = chat_session.send_message(input_content)
            # print(response.candidates[0].content)
            response_text = ""
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text and part.thought is not True:
                    response_text += part.text

            # 更新短期记忆库
            self.short_term_memory.append({"role": "user", "text": user_text, "timestamp": time.time()})
            self.short_term_memory.append({"role": "model", "text": response_text, "timestamp": time.time()})

            return response_text
        except Exception as e:
            return f"Amaya 核心逻辑异常: {str(e)}"


    async def tidying_up(self):
        """
        [自主整理模式]
        这是你的"潜意识整理时间"。
        不接收用户输入，而是自我反思文件结构。
        """
        try:
            print("Amaya 正在进行自主整理...")
            context = get_global_context_string()
            maintenance_prompt = f"""
[System Maintenance Mode]
Context:
{context}

Task:
1. 如果有太多零散的日记, 请将它们按日期合并为一个类似 `journal_summary_2025_12.md` 的文件, 并归档旧文件。
2. 如果有过期的任务, 请将其删除。
3. 注意不要在操作中删除有价值的信息。
4. ["routine.json", "plan.md", "user_profile.md", "current_goals.md"] 是默认存在的文件, 你不应该归档它们, 但可以修改内容。

只执行必要的操作。如果没有什么要改的，就回答"System clean."。
"""

            chat_session = self._create_chat()
            response = chat_session.send_message(maintenance_prompt)
            response_text = ""
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text and part.thought is not True:
                    response_text += part.text

            return f"整理报告: {response_text}"
        except Exception as e:
            return f"整理失败: {str(e)}"


amaya = AmayaBrain()
