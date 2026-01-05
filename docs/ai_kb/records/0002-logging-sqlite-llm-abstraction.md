# 0002 日志结构化与 SQLite 存储改造

- 日期: 2026-01-05
- 状态: active
- 负责人: AI
- 变更类型: refactor / infra
- 影响范围: utils/logging_setup.py, core/llm/openai.py, core/llm/gemini.py, core/agent.py, utils/storage.py, scripts/db_inspect.py, config.py, main.py, .env.example
- 关联: 需求讨论（日志/多用户预期/存储升级）
- 约束与风险: 迁移逻辑需确保旧 JSON 数据可读且不丢失；全量日志可能暴露敏感信息
- 环境/版本: Python 3.10+

## 0. 问题/目标 (Context)
需要提升日志可观测性（预览 + 可选全量记录）、按时间分割并分文件存储，同时将事件总线/提醒/短期记忆迁移到 SQLite 以便调试与后续扩展；并消除 Agent 对 OpenAI SDK 的直接依赖。

## 1. 方案对比 (Options)
### 方案 A
- 优点: 改动最小，保持 JSON 文件存储与现有日志配置
- 缺点: 事件总线清空方式不利于调试，日志难以关联与分层
- 成本: 低

### 方案 B
- 优点: SQLite 可查询/审计，日志分层且带 request_id，支持可选全量记录
- 缺点: 需要迁移逻辑与新工具脚本
- 成本: 中

## 2. 决策 (Decision)
选择方案 B。目标是兼顾调试便利性与后续多用户扩展的可操作性，同时保持现有文件型记忆系统不变。

## 3. 设计与实现 (Design & Implementation)
- LLM 抽象：将音频转写逻辑下沉到 OpenAI Provider，Agent 不再直接依赖 OpenAI SDK。
- 日志：引入 request_id 关联，按模块分文件（app/llm/event/error/payload），按天轮转；payload 以 JSON 行输出。
- 存储：meta/pending_reminders/short_term_memory/sys_events 迁移到 SQLite，事件读取标记 processed/invalid；保留旧 JSON 文件作为回退。
- 调试：新增 `scripts/db_inspect.py` 查询 DB 表与样例数据。

## 4. 实验与效果 (Experiment & Result)
N/A：未执行运行验证，仅完成代码改造与配置项补充。

## 5. 测试与优化 (Tests & Optimization)
- [ ] 单元测试:
- [ ] 集成测试:
- [ ] 手动验证:
- 结果/备注: N/A（需在本地启动后验证迁移与日志输出）

## 6. 结论与收获 (Lessons)
将高频调试数据与业务数据分层记录能显著降低排障成本；同时保持 file-based memory 不变，避免破坏既有心智模型。

## 7. 后续行动 (Next)
- 验证 SQLite 迁移与提醒恢复流程是否一致
- 明确多用户隔离方案（ID -> 记忆库与提醒空间的映射）
