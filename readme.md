# Amaya - 一个为日程规划与提醒调优的人性化Agent

## 项目思路

这个项目本质是实现了一个Agent。为了简化实现，通过让模型自主管理本地的文件来构建属于用户的长期记忆。通过特制的上下文与强鲁棒性的持久化机制，提供科学的、协商式的日程管理与多模态情感陪伴；她不是只会听令的工具，而是一个拥有冷静“AI 气色”、能主动感知你生活状态、且承诺永远不会因重启而丢失提醒的硅基老友。

## 具体方案

### 核心特性
- **文件即记忆 (File-based Memory)**: Amaya 的长期记忆直接存储为 Markdown/JSON 文件。你可以直接查看、编辑这些文件，完全掌控 AI 的记忆。
- **鲁棒的提醒系统 (Robust Reminder)**: 基于事件总线 (`sys_event_bus.jsonl`) 和持久化存储 (`pending_reminders.json`)。即使系统崩溃或重启，未完成的提醒也会在下次启动时自动恢复。
- **多 LLM 支持**: 支持 Gemini 和 OpenAI (ChatGPT) 两种后端，可通过配置切换。支持第三方 Base URL，方便使用代理服务。
- **双模型架构**: 采用快速模型处理日常响应，高级模型处理复杂思考，平衡速度与智能。

### 快速开始

1. **环境准备**: Python 3.10+, Telegram Bot Token, LLM API Key (Gemini 或 OpenAI)
2. **安装依赖**: `pip install -r requirements.txt`
3. **配置**: 复制 `.env.example` 为 `.env` 并填入配置:
   - `TELEGRAM_BOT_TOKEN`: Telegram 机器人 Token
   - `OWNER_ID`: 你的 Telegram 用户 ID
   - `LLM_PROVIDER`: 选择 `gemini` 或 `openai`
   - 对应的 API Key 和可选的 Base URL；如使用 OpenAI 的 gpt-5.x 可设置 `OPENAI_REASONING_EFFORT=medium|high` 以启用 reasoning
4. **运行**: `python main.py`

### 目录结构
- `core/`: 核心逻辑 (Agent, 调度器, 工具集)
- `data/`: 数据存储 (记忆库, 事件总线)
- `utils/`: 通用工具 (文件IO, 存储管理)

### 交互指南
- **日常对话**: 像朋友一样聊天。
- **设置提醒**: "10分钟后提醒我喝水" 或 "明天早上8点叫醒我"。
- **记忆管理**: "记住我的车牌号是..." (Amaya 会自动存入文件)。
