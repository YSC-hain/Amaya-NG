# 0003 多用户与配置整理、知识库重命名

- 日期: 2026-01-05
- 状态: active
- 负责人: AI
- 变更类型: refactor / infra / docs
- 影响范围: adapters/*, core/*, utils/*, config.py, .env.example, docs/ai_knowledge_base/*, readme.md
- 关联: 用户需求（多用户、配置外提、知识库重命名）
- 约束与风险: 多用户映射需保证一致性；日志全量记录可能包含敏感内容
- 环境/版本: Python 3.10+

## 0. 问题/目标 (Context)
需要支持少量多用户，同时把更多硬编码参数集中到配置；并将 ai_kb 更直观命名，保证文档可读。

## 1. 方案对比 (Options)
### 方案 A
- 优点: 继续单用户 + 文件存储，改动最少
- 缺点: 无法隔离用户数据，难以扩展
- 成本: 低

### 方案 B
- 优点: 统一 user_id 映射 + SQLite 维度，便于扩展与调试
- 缺点: 需要迁移与上下文传递
- 成本: 中

## 2. 决策 (Decision)
选择方案 B。引入 user_id 维度并保持记忆文件在文件系统中按用户隔离。

## 3. 设计与实现 (Design & Implementation)
- 新增 `utils/user_context.py`，通过上下文携带当前 user_id。
- SQLite 表新增 user_id 维度，增加 `users` 与 `user_mappings` 表。
- 记忆文件路径调整为 `data/memory_bank/<user_id>/`。
- 提醒、短期记忆、事件总线按 user_id 隔离。
- 多项硬编码参数外提到 `config.py` 和 `.env.example`。
- 将 `docs/ai_kb` 重命名为 `docs/ai_knowledge_base` 并更新引用。

## 4. 实验与效果 (Experiment & Result)
N/A：尚未进行运行验证。

## 5. 测试与优化 (Tests & Optimization)
- [ ] 单元测试:
- [ ] 集成测试:
- [ ] 手动验证:
- 结果/备注: N/A

## 6. 结论与收获 (Lessons)
多用户最小可行方案应优先保证数据隔离与可追溯，性能可在后续逐步优化。

## 7. 后续行动 (Next)
- 验证多用户提醒恢复与发送链路
- 明确用户映射与权限策略（允许列表/自动注册）
