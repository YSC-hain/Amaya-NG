# Amaya-NG — 面向日程管理与情感陪伴的友伴型 Agent

## 项目愿景
我们不再追求“无限接近真人”，而是打造一个更像朋友的智能体：
既能接住情绪、主动发起话题，也能管理日程、协助安排时间并可靠提醒。

## 设计原则
- **文件即记忆 (File-based Memory)**: 重要记忆直接落到 Markdown/JSON，可读可控。
- **鲁棒提醒 (Robust Reminder)**: 事件总线 + 持久化提醒，崩溃重启也不丢提醒。
- **多 LLM 支持**: Gemini / OpenAI 双后端，配置可切换。
- **双模型策略**: 快速模型处理日常，高级模型处理复杂思考。

## 面向 AI 的知识库（Docs 体系）
本项目采用“解耦系统 + 项目融合数据”的方式：
知识库体系本身可复用，但每次记录都会把项目经验沉淀进去。

- 入口：`docs/ai_kb/README.md`
- 总览：`docs/ai_kb/index.md`
- 记录：`docs/ai_kb/records/`（严格模板）
- 模板：`docs/ai_kb/templates/record_template.md`
- AI 记录规范：`docs/ai_kb/AI_RECORDING_GUIDE.md`

## 快速开始
1. **环境准备**: Python 3.10+, Telegram Bot Token, LLM API Key (Gemini 或 OpenAI)
2. **安装依赖**: `pip install -r requirements.txt`
3. **配置**: 复制 `.env.example` 为 `.env` 并填入配置:
   - `TELEGRAM_BOT_TOKEN`: Telegram 机器人 Token
   - `OWNER_ID`: 你的 Telegram 用户 ID
   - `LLM_PROVIDER`: 选择 `gemini` 或 `openai`
   - 对应的 API Key 和可选的 Base URL；如使用 OpenAI 的 gpt-5.x 可设置 `OPENAI_REASONING_EFFORT=medium|high`
4. **运行**: `python main.py`

## 目录结构
- `core/`: 核心逻辑 (Agent, 调度器, 工具集)
- `data/`: 数据存储 (记忆库, 事件总线)
- `docs/`: 文档（含 AI 知识库、LLM 调用链等）
- `utils/`: 通用工具 (文件 IO, 存储管理)

## 交互指南
- **日常对话**: 像朋友一样聊天。
- **设置提醒**: "10分钟后提醒我喝水" 或 "明天早上8点叫醒我"。
- **记忆管理**: "记住我的车牌号是..." (Amaya 会自动存入文件)。
