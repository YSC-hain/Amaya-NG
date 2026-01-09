# ROADMAP（v0.4）- 从零重建的分阶段验收路线（交互式）

## 总原则
- 每个 Phase 先给 Proposal，用户审核后实现
- 每个 Phase 结束必须可运行、可回滚、可验收

---

## Phase 1：状态骨架与只读 plan.md
目标：
- 建立 data/ 目录状态模型（plan.json / plan.md / kb / meta）
- 实现 plan 结构化工具最小集：ensure_list/ensure_group/add_task/update_task/set_schedule/render_md
验收：
- 任意新增/修改任务均通过工具写 plan.json，并正确渲染 plan.md
- 禁止直接写 plan.md（代码层面限制）

---

## Phase 2：提醒派生与恢复
目标：
- 实现 reminders.json
- 实现 reminder.sync_from_plan（内部）
- 实现 ReminderService：启动扫描、注册、到点触发事件注入
验收：
- set_reminder 后 reminders.json 自动出现对应条目
- 重启后仍能恢复并触发
- 允许远期 reminder（>24h）

---

## Phase 3：Runtime LLM 规划决策闭环
目标：
- Orchestrator 串行流水线打通：读取上下文 -> LLM -> 工具循环 -> 渲染 -> 同步提醒
- 在 PROMPTS 的规则下：LLM 自行决定是否触发规划动作
验收：
- 纯闲聊不改计划；出现任务/提醒诉求能正确落盘
- 日期-only + 要提醒：落软性 + next_review_at（不猜时间）

---

## Phase 4：KB 模板与 projects 档案
目标：
- preferences/goals/projects 模板落地
- kb.upsert merge 策略实现（防结构被破坏）
验收：
- preferences 中包含固定默认 timezone：Asia/Shanghai
- projects/<slug>.md 可创建、可更新，且不替代 plan
