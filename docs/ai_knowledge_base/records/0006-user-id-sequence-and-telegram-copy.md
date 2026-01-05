# 0006 用户编号改为六位自增与 Telegram 文案修复

- 日期: 2026-01-05
- 状态: active
- 负责人: AI
- 变更类型: feature
- 影响范围: utils/storage.py, adapters/telegram_bot.py
- 关联: /user_create 输出异常文案、user_id 过长
- 约束与风险: 六位序号上限 999999，超过将导致新用户创建失败。
- 环境/版本: Python 3.12, sqlite3

## 0. 问题/目标 (Context)
`/user_create` 返回了破损的文案（????），且 user_id 使用 UUID 不便人工输入和管理。需要恢复可读文案，并将 user_id 设计为六位数字自增。

## 1. 方案对比 (Options)
### 方案 A
- 优点: 继续使用 UUID，避免序号上限与并发冲突。
- 缺点: user_id 过长，不便手工操作与沟通。
- 成本: 无改动。

### 方案 B
- 优点: 使用数据库查询最大数值 +1，生成固定六位数字，易读易用。
- 缺点: 需处理上限与潜在并发；超过上限需额外策略。
- 成本: 低。

## 2. 决策 (Decision)
采用方案 B，六位数字自增，并对创建失败场景做日志与提示。

## 3. 设计与实现 (Design & Implementation)
- `_create_user_id` 改为基于 users 表内最大数字 ID +1，格式化为 6 位。
- `create_user` 返回 Optional 并在失败时记录日志。
- `/user_create` 增加失败提示，修正文案与帮助信息。
- 修复 `/whoami` 与 `/user_link` 的损坏文案。

## 4. 实验与效果 (Experiment & Result)
N/A：未执行端到端验证，仅完成代码与逻辑审查。

## 5. 测试与优化 (Tests & Optimization)
- [ ] 单元测试: N/A（无现成测试框架）
- [ ] 集成测试: N/A（需 Telegram 环境）
- [ ] 手动验证: 未执行
- 结果/备注: 需在实际 Bot 中验证 `/user_create` 与 `/whoami` 输出。

## 6. 结论与收获 (Lessons)
面向用户的 ID 需要兼顾可读性与可维护性，设计序号方案时必须明确上限与异常路径。

## 7. 后续行动 (Next)
考虑补充序号耗尽后的扩展策略或配置化位数。
