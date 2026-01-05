# Amaya-NG — 面向日程管理与情感陪伴的友伴型 Agent

## 项目愿景
我们不再追求“无限接近真人”，而是打造一个更像朋友的智能体：
既能接住情绪、主动发起话题，也能管理日程、协助安排时间并可靠提醒。
核心服务对象是大学生（大一新生场景优先），重点解决课程表与学习计划的复杂性。

## 设计原则
- **文件即记忆 (File-based Memory)**: 重要记忆直接落到 Markdown/JSON，可读可控。
- **鲁棒提醒 (Robust Reminder)**: 事件总线 + 持久化提醒，崩溃重启也不丢提醒。
- **多 LLM 支持**: Gemini / OpenAI 双后端，配置可切换。
- **双模型策略**: 快速模型处理日常，高级模型处理复杂思考。

## 结构化日程表（重点）
- `routine.json` 作为通用的结构化日程表使用。
- 以“具体到每天”的日程项为核心，涵盖课程/自习/活动等场景。
- 调整或维护视作日程变更，与提醒系统联动即可满足课表需求。
- 不做单双周/周次推导，统一以“具体日期”表达。
- 如需保留原始课表，可放在 `course_schedule.md`，再按需提取未来 2-3 天写入 `routine.json`。
- 提供日程表工具函数（查看/新增/更新/移动/删除/清空）供 LLM 直接操作。
- 结构示例（简化）：
  - `days[]`：按天记录，字段 `date` + `items[]`
  - `items[]`：`id`, `start`, `end`, `title`, `location`, `note`, `tags`

## 面向 AI 的知识库（Docs 体系）
本项目采用“解耦系统 + 项目融合数据”的方式：
知识库体系本身可复用，但每次记录都会把项目经验沉淀进去。

- 入口：`docs/ai_knowledge_base/README.md`
- 总览：`docs/ai_knowledge_base/index.md`
- 记录：`docs/ai_knowledge_base/records/`（严格模板）
- 模板：`docs/ai_knowledge_base/templates/record_template.md`
- AI 记录规范：`docs/ai_knowledge_base/AI_RECORDING_GUIDE.md`

## 快速开始
1. **环境准备**: Python 3.10+, Telegram Bot Token, LLM API Key (Gemini 或 OpenAI)
2. **安装依赖**: `pip install -r requirements.txt`
3. **配置**: 复制 `.env.example` 为 `.env` 并填入配置:
   - `TELEGRAM_BOT_TOKEN`: Telegram 机器人 Token
   - `REQUIRE_AUTH`: 是否启用访问控制（默认 true）
   - `OWNER_ID` / `ADMIN_USER_IDS` / `ALLOWED_USER_IDS`: 允许访问的 Telegram 用户 ID
   - `LLM_PROVIDER`: 选择 `gemini` 或 `openai`
   - 对应的 API Key 和可选 Base URL
4. **运行**: `python main.py`

## 目录结构
- `adapters/`: 平台适配层（当前为 Telegram）
- `core/`: 核心逻辑（Agent、调度器、工具集、LLM 抽象层）
- `data/`: 数据存储（SQLite、记忆文件等）
- `docs/`: 文档（含知识库、LLM 调用链等）
- `utils/`: 通用工具（日志、存储、用户上下文等）

## 多用户支持（轻量级）
- 通过 `users` 与 `user_mappings` 表实现平台 ID -> 内部 user_id 的映射。
- 记忆文件按 `data/memory_bank/<user_id>/` 分目录隔离。
- 提醒、短期记忆、事件总线均带 `user_id` 字段。
- 访问控制默认开启（`REQUIRE_AUTH=true`），需要配置允许列表。

## 记忆系统概览
- **记忆库文件**：`data/memory_bank/<user_id>/` 下的 Markdown/JSON。
- **默认可见文件**：`routine.json`, `plan.md`, `user_profile.md`, `current_goals.md`。
- **课表源文件（可选）**：`course_schedule.md`，用于生成未来 2-3 天的日程。
- **Pinned 文件**：由 `meta` 表记录，拼接进全局上下文。
- **短期记忆**：SQLite 表 `short_term_memory`，用于近期对话缓存。
- **提醒与事件**：`pending_reminders` 与 `sys_events` 表负责任务与事件恢复。

## 部署步骤（用户创建与绑定）
1. 在 `.env` 中配置管理员：
   - `OWNER_ID` 或 `ADMIN_USER_IDS` 至少配置一个，否则所有访问会被拒绝。
2. 启动后管理员在 Telegram 里执行：
   - `/user_create [display_name]` 创建用户，获得 `user_id`
   - `/user_link <telegram_id> <user_id> [display_name] [--force]` 绑定 Telegram ID
3. 用户可执行 `/whoami` 查看当前绑定关系。
4. 记忆文件路径：
   - 记忆文件位于 `data/memory_bank/<user_id>/`，按 user_id 隔离；
   - 如需导入历史文件，请手动放入对应目录。

## 日志与调试
- 日志按天分割、分文件输出：
  - `amaya.app.log`, `amaya.llm.log`, `amaya.events.log`, `amaya.error.log`, `amaya.llm.payload.log`
- `LOG_LLM_PAYLOADS=full` 时记录 LLM 原文输入/输出（注意敏感信息）。
- SQLite 快速查看：`python scripts/db_inspect.py`

## 交互指南
- **日常对话**: 像朋友一样聊天。
- **设置提醒**: "10分钟后提醒我喝水" 或 "明天早上8点叫醒我"。
- **记忆管理**: "记住我的车牌号是..." (Amaya 会自动存入文件)。
