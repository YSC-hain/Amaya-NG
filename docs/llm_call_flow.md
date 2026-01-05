# LLM 调用链与 Prompt 组装说明

本文档梳理从用户输入到 LLM 调用、再到工具调用与响应返回的完整链路，重点说明提示词拼装与多模态输入的处理方式。

## 入口与消息流向
- **适配器层**：以 Telegram 为例，消息在 `adapters/telegram_bot.py` 中被统一丢入 `ChatSessionBuffer`，最终调用 `amaya.chat_sync(...)`。
- **核心 Agent**：`core/agent.py` 的 `AmayaBrain.chat_sync` 负责整理上下文、选择模型、调用 LLM，并维护短期记忆。
- **LLM 抽象层**：`core/llm/base.py` 定义统一接口；工厂 `core/llm/factory.py` 根据配置创建具体 Provider（OpenAI/Gemini）。
- **Provider 实现**：`core/llm/openai.py` 与 `core/llm/gemini.py` 按各自 API 协议组装请求，执行工具调用循环并返回 `ChatResponse`。
- **多用户上下文**：适配器会解析平台用户并映射到内部 `user_id`，通过上下文隔离记忆与提醒数据。

## 运行模式与调用路径
- **日常对话**：Telegram 适配器经 `chat_handler/photo_handler/voice_handler` → `ChatSessionBuffer` 聚合 → `AmayaBrain.chat_sync` → Provider。
- **清理模式（tidying_up）**：定时任务调用 `AmayaBrain.tidying_up`，以维护提示词 + 全局上下文构造 `MultimodalInput`，强制使用 smart 模型；`TIDYING_DRY_RUN=true` 时禁用工具，避免写盘。
- **快速连发缓冲**：`RAPID_MESSAGE_BUFFER_SECONDS` 控制同会话消息合并时长，由 buffer 将合并后的内容再进入 `chat_sync`。
- **模型切换**：包含图片/音频或出现“plan/规划”等关键词时走 smart 模型；`OPENAI_REASONING_EFFORT` 仅在 smart 模式下启用。

## Prompt 组装与上下文
1. **全局上下文**：`utils.storage.get_global_context_string` 注入全局记忆（受 `GLOBAL_CONTEXT_MAX_CHARS` 限制）。
2. **世界背景**：`AmayaBrain.get_world_background` 注入当前时间等环境信息。
3. **用户输入**：合并为 `full_input`，格式如下：
```
[WORLD CONTEXT]
...全局记忆...

[WORLD BACKGROUND]
...时间/日期...

[USER INPUT]
...原始用户消息或经语音转写后的文本...
```
4. **系统提示词**：来自 `config.CHAT_SYSTEM_PROMPT`，在 Provider 侧作为 system 消息传入。
5. **历史记忆**：`_get_cleaned_history` 生成的 `ChatMessage` 列表，控制过期与数量上限后作为对话历史。

## 多模态输入策略
- `MultimodalInput` 同时承载文本、图片和音频。
- **语音**：当 Provider 为 OpenAI 时先用 Whisper（`OpenAIProvider.transcribe_audio`）转写；转写失败直接提示用户。
- **图片**：
  - OpenAI：在 `_build_multimodal_content` 中转换为 `data:image/jpeg;base64,...` 格式，仅在请求体内使用，不会写入日志。
  - Gemini：直接构造 `PIL.Image` 对象作为 Part。
- **模型选择**：若含图片/音频，或用户消息包含“规划/plan”等关键词，`use_smart_model=True` 以启用更强模型。

## 工具调用与循环
1. Provider 初始请求包含系统提示词、历史消息以及当前多模态输入。
2. 模型触发工具调用时：
   - OpenAI：`responses.create` 返回 `function_call` 项，`OpenAIProvider` 逐个执行，并把输入/输出追加到 `conversation_input` 后继续循环。
   - Gemini：通过 `automatic_function_calling` 配置，SDK 自动驱动工具调用，输出由 Provider 聚合。
3. 循环受 `max_tool_calls` 限制（默认 10），最终得到纯文本响应。

## 日志记录（隐私安全）
- Agent 层仅记录模型选择、耗时等元数据，不写入图片或完整文本。
- OpenAI Provider 使用 `_truncate_for_log` 与 `_format_arguments_for_log`：
  - 请求日志仅展示文本预览（默认 300 字）、是否含图片/音频、工具名列表。
  - 工具调用日志会输出工具名、脱敏后的参数（单行、截断）与输出摘要（默认 200 字），满足“工具名/参数/工具回复”观测需求。
  - 完成日志记录响应预览（默认 400 字）及工具调用次数。
- 设计目标：避免 Base64 图像字符串或敏感长文本出现在日志中，同时保留可观测性。

## 快速排查指南
- **模型切换**：检查 `.env` 中的 `LLM_PROVIDER`、`*_SMART_MODEL`、`*_FAST_MODEL` 与 `OPENAI_REASONING_EFFORT`。
- **无输出/空回复**：Provider 会回退为 `"抱歉，我暂时无法回应。"`，可在日志中搜索 `OpenAI chat 完成` / `Gemini Provider 异常` 关键词定位。
- **工具未触发**：确认工具函数已在 `core.tools.tools_registry` 注册，并传入 `AmayaBrain.chat_sync` → Provider `tools` 参数。
