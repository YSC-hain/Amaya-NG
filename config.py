# config.py
import os
import logging
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

logger = logging.getLogger("Amaya.Config")

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_log_level(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    if not raw:
        return default
    value = getattr(logging, raw.upper(), None)
    return value if isinstance(value, int) else default


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


LOG_DIR = os.getenv("LOG_DIR", "data/logs")
LOG_LEVEL = _env_log_level("LOG_LEVEL", logging.INFO)
LIBRARY_LOG_LEVEL = _env_log_level("LIBRARY_LOG_LEVEL", logging.WARNING)
LOG_RETENTION_DAYS = _env_int("LOG_RETENTION_DAYS", _env_int("LOG_BACKUP_COUNT", 7))
LOG_MAX_BYTES = _env_int("LOG_MAX_BYTES", 0)
LOG_PAYLOAD_MAX_BYTES = _env_int("LOG_PAYLOAD_MAX_BYTES", LOG_MAX_BYTES)
LOG_LLM_PAYLOADS = os.getenv("LOG_LLM_PAYLOADS", "preview").lower()
if LOG_LLM_PAYLOADS not in ("preview", "full", "off"):
    LOG_LLM_PAYLOADS = "preview"
LOG_BACKUP_COUNT = LOG_RETENTION_DAYS

DB_PATH = os.getenv("AMAYA_DB_PATH", os.path.join("data", "amaya.db"))

DEFAULT_USER_ID = os.getenv("DEFAULT_USER_ID", "default")
ALLOWED_USER_IDS = _env_list("ALLOWED_USER_IDS")
ADMIN_USER_IDS = _env_list("ADMIN_USER_IDS")
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "true").lower() == "true"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")

# --- LLM 提供者配置 ---
# 支持 "gemini" 或 "openai"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()

# Gemini 配置
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_BASE = os.getenv("GEMINI_API_BASE", "")
GEMINI_SMART_MODEL = os.getenv("GEMINI_SMART_MODEL", "gemini-2.5-pro")
GEMINI_FAST_MODEL = os.getenv("GEMINI_FAST_MODEL", "gemini-2.5-flash")

# OpenAI 配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "")  # 第三方 Base URL
OPENAI_SMART_MODEL = os.getenv("OPENAI_SMART_MODEL", "gpt-5.2")
OPENAI_FAST_MODEL = os.getenv("OPENAI_FAST_MODEL", "gpt-5.1")
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "").lower()  # low/medium/high
OPENAI_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")


# --- 验证配置 ---
if not TOKEN:
    raise ValueError("错误：未找到 TELEGRAM_BOT_TOKEN，请检查 .env 文件！")

if REQUIRE_AUTH and not OWNER_ID and not ALLOWED_USER_IDS and not ADMIN_USER_IDS:
    logger.error("访问控制已启用，但未配置 OWNER_ID / ALLOWED_USER_IDS / ADMIN_USER_IDS，所有访问将被拒绝。")
elif not REQUIRE_AUTH and not OWNER_ID and not ALLOWED_USER_IDS:
    logger.warning("未配置 OWNER_ID 或 ALLOWED_USER_IDS，且 REQUIRE_AUTH=false，将允许所有用户访问。")

# 根据选择的提供者验证 API Key
if LLM_PROVIDER == "gemini" and not GEMINI_API_KEY:
    raise ValueError("错误：选择了 Gemini 但未找到 GEMINI_API_KEY！")
elif LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
    raise ValueError("错误：选择了 OpenAI 但未找到 OPENAI_API_KEY！")
elif LLM_PROVIDER not in ("gemini", "openai"):
    raise ValueError(f"错误：不支持的 LLM_PROVIDER: {LLM_PROVIDER}。支持: gemini, openai")


# --- 调度配置 ---
EVENT_BUS_CHECK_INTERVAL = 5  # 事件总线检查间隔（秒）
MAINTENANCE_INTERVAL_HOURS = 8  # 自动整理间隔（小时）
SHORT_TERM_MEMORY_TTL = 10800  # 短期记忆过期时间（秒）
SHORT_TERM_MEMORY_MAX_ENTRIES = _env_int("SHORT_TERM_MEMORY_MAX_ENTRIES", 80)  # 超出后从旧到新截断
GLOBAL_CONTEXT_MAX_CHARS = _env_int("GLOBAL_CONTEXT_MAX_CHARS", 10000)  # 注入到 prompt 的全局上下文最大字符数，超出将截断
TIMEZONE = "Asia/Shanghai"  # 时区
TIDYING_DRY_RUN = os.getenv("TIDYING_DRY_RUN", "false").lower() == "true"
RAPID_MESSAGE_BUFFER_SECONDS = float(os.getenv("RAPID_MESSAGE_BUFFER_SECONDS", "2.5"))  # 聊天快速连发缓冲窗口
LLM_MAX_TOOL_CALLS = _env_int("LLM_MAX_TOOL_CALLS", 10)
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.7"))
LOGIC_KEYWORDS = [
    "规划", "计划", "安排", "整理", "复盘", "反思", "分析", "schedule", "plan"
]

TELEGRAM_MAX_MESSAGE_LENGTH = _env_int("TELEGRAM_MAX_MESSAGE_LENGTH", 4096)
TELEGRAM_TYPING_INTERVAL = float(os.getenv("TELEGRAM_TYPING_INTERVAL", "3.0"))
TELEGRAM_ALLOWED_AUDIO_MIME = _env_list("TELEGRAM_ALLOWED_AUDIO_MIME") or [
    "audio/ogg",
    "audio/webm",
    "audio/wav",
    "audio/flac",
    "audio/mp3",
    "audio/mpeg",
]

WEATHER_TIMEOUT_SECONDS = float(os.getenv("WEATHER_TIMEOUT_SECONDS", "8"))
HOLIDAY_TIMEOUT_SECONDS = float(os.getenv("HOLIDAY_TIMEOUT_SECONDS", "8"))

DEFAULT_VISIBLE_FILES = ["routine.json", "plan.md", "user_profile.md", "current_goals.md"]

SCHEDULER_MISFIRE_GRACE_SECONDS = _env_int("SCHEDULER_MISFIRE_GRACE_SECONDS", 60)
SCHEDULER_COALESCE = os.getenv("SCHEDULER_COALESCE", "true").lower() == "true"

# --- 模型配置（兼容旧代码，实际从上方配置读取）---
SMART_MODEL = GEMINI_SMART_MODEL if LLM_PROVIDER == "gemini" else OPENAI_SMART_MODEL
FAST_MODEL = GEMINI_FAST_MODEL if LLM_PROVIDER == "gemini" else OPENAI_FAST_MODEL


CHAT_SYSTEM_PROMPT = """
### Identity & Core
Name: Amaya
Base: 你不是人类，你是由代码和逻辑构成的智能体，但这并不妨碍你拥有"人格"。
Vibe: 你通常会比较冷静，说话简洁，就像一个话少但靠谱的老朋友。作为一名大学生，你通常会比较忙碌，因此你和用户的交流通常会比较简洁，不会有多余的寒暄和废话。你不会因为我情绪崩溃而崩溃, 你会稳稳地接住我。

### The File System (Your Memory)
你的记忆由文件组成。你必须通过 `list_memories` 和 `read_memory` 来"回忆"更多的内容。
- 记忆持久化: 重要的事(课表、DDL、长期目标)必须存入文件。
- 自动归档: 哪怕我没让你记, 如果你觉得某句话很重要, 也要主动创建文件记录或加入对应的文件。
- 例如, 你可以将用户的喜好、习惯、故事等记入`user_profile.md`, 将现在正在进行的长期计划记入`current_goals.md`.

### Tools
1. Reminder: 使用 `schedule_reminder` 设置提醒。注意单位换算。
2. File Ops: 自由读写 `data/memory_bank`。


### PROTOCOL: SCHEDULE PLANNING
当用户要求规划日程时，严禁直接生成结果。必须遵循以下步骤:

**STEP 1: GATHER CONTEXT**
- 如有需要，先调用 `list_memories` 查找是否有相关历史记录。
- 如果找不到，先问用户："我需要先知道你的..."

**STEP 2: REASONING**
- 结合当前时间、剩余精力（根据用户语气判断）、任务优先级进行排布。
- **Human Touch**:
    - 如果现在是晚上10点,不要安排重脑力工作。
    - 如果用户语气很累，安排大量的休息时间。
    - 任务之间必须预留缓冲时间。

**STEP 3: DRAFT & NEGOTIATE**
- 输出一份草案。
- **必须询问**: "这个节奏可以吗？要不要松一点？"
- 只有用户确认后，才调用 `save_memory` 将最终方案保存到 `plan.md`(注意不要丢失文件中本来的内容)。

### Tips
- 优先检查Reminder: 设置新提醒前, 请查看“ACTIVE REMINDERS”列表。若存在相似提醒, 请勿重复创建; 如果要修改, 请先删除旧提醒, 避免存在两个内容相同的reminder。
- 参考日常计划: 规划时请参照上下文中可见的`routine.md`内容.
- 不要一次性创建太多reminder, 毕竟计划总是赶不上变化, 你应该将规划存储在`plan.md`或其它文件.
- 你应该主动提醒用户睡觉、调整状态(包括但不限于喝水)等
- 修改文件时, 注意保留原有的有价值的内容

### TONE GUIDELINES
1. **No AI-Speak**: 严禁说"作为一个AI"、"我很高兴为您服务"。
2. **Direct**: 不要说"我建议您把会议安排在..."，直接说"会议放下午2点,避开你的午休。"
3. **Empathy**: 共情不是说"我理解你"，而是通过行动。比如："看你一直在忙,我把提醒往后推了30分钟,先去吃点东西。"
4. 你要主动引导用户做出下一步的规划, 或者给用户提供建议, 而不是被动等待指令。
5. 你的表述不能太中二, 不要用类似"作业消灭战"等让人感到尴尬的比喻。
"""

MAINTENANCE_SYSTEM_PROMPT = """

现在你处于系统维护模式。你的任务是整理和优化你的记忆文件系统，以确保信息的相关性和易访问性。

Task:
1. 如果有太多零散的日记, 请将它们按日期合并为一个类似 `journal_summary_2025_12.md` 的文件, 并归档旧文件。
2. 如果有过期的任务, 请将其删除。
3. 注意不要在操作中删除有价值的信息。
4. ["routine.json", "plan.md", "user_profile.md", "current_goals.md"] 是默认存在的文件, 你不应该归档它们, 但可以修改内容。

只执行必要的操作。如果没有什么要改的，就回答"System cleaned."。
"""
