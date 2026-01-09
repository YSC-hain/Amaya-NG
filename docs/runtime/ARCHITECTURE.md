# ARCHITECTURE（v0.4）- 单用户 / 串行 / 规划为主、提醒派生

## 0. 两种 LLM（禁止混淆）
- Runtime LLM：运行时对话/规划/工具调用
- Builder LLM：开发/重构/文档（受强约束）

---

## 1. 系统目标（本阶段）
1) 拟真：提醒与规划在对话中自然发生
2) 可控：串行执行，少并发，便于审计
3) 可靠：系统托管提醒可恢复
4) 结构化：计划可被结构化操作（接入 Dida365 的前提）

---

## 2. 模块（最小集合）
### 2.1 Adapter（平台适配，如 Telegram）
- 接收用户输入（文本/图/语音）
- 转交 Orchestrator
- 发送 Orchestrator 的最终输出

### 2.2 Orchestrator（核心串行流水线）
职责：
- 读取状态快照（plan/reminders/kb/meta）
- 调用 Runtime LLM（含工具调用循环）
- 串行执行工具调用并写回状态
- 渲染 plan.md（只读视图）
- 同步派生 reminders.json

### 2.3 Runtime LLM（对话 + 规划决策）
职责：
- 生成陪伴型对话回复
- 决定是否触发“规划动作”
- 通过结构化工具更新 plan.json
- 在需要时把软性规划转硬性规划（set_reminder）

### 2.4 StateStore（状态存储）
- plan.json：唯一真相源（结构化）
- plan.md：只读渲染视图
- reminders.json：系统托管提醒真相源（派生/同步）
- kb/：知识库（模板化）

### 2.5 ReminderService（调度与送达）
- 扫描 reminders.json 注册任务
- 到点触发时向 Orchestrator 注入系统事件
- 由 Runtime LLM 动态生成提醒话术（默认），并发送
- 高优先级可触发多渠道/ask（策略未定稿前不启用）

---

## 3. “规划为主、提醒派生”的核心原则
- 计划是主：用户的任务安排与变更都落在 plan.json
- 提醒是派生执行层：系统从 plan.json 中“带 reminder 的任务”派生 reminders.json
- Runtime LLM 不直接维护 reminders.json 的生命周期细节（减少失控面）

---

## 4. 运行时串行流程（每条用户消息）
1) Adapter 收到消息
2) Orchestrator 读取上下文（plan/reminders/kb/meta）
3) Orchestrator 调用 Runtime LLM
4) 如 LLM 决定规划：调用 plan 工具写 plan.json
5) 渲染 plan.md（只读视图）
6) reminder.sync_from_plan：派生/同步 reminders.json
7) 返回最终回复给用户

---

## 5. 提醒触发流程
1) ReminderService 到点触发某条 reminder
2) 注入 [SYSTEM_REMINDER_EVENT]（包含 reminder_id, task_id, priority 等）
3) Orchestrator 调用 Runtime LLM 生成“拟真提醒话术”（默认动态生成）
4) Adapter 发送给用户
5) 更新 reminders.json 状态（sent/acknowledged 等）
