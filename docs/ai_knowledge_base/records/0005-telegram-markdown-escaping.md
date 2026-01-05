# 0005 Telegram Markdown 转义与命令回复容错

- 日期: 2026-01-05
- 状态: active
- 负责人: AI
- 变更类型: bugfix
- 影响范围: adapters/telegram_bot.py
- 关联: /user_create 报错 "Can't parse entities"
- 约束与风险: 仍依赖 Telegram Markdown；LLM 输出仍可能触发格式错误，已保留回退为纯文本的容错。
- 环境/版本: Python 3.12, python-telegram-bot 20.x

## 0. 问题/目标 (Context)
部署时执行 `/user_create` 报错 Telegram Markdown 解析失败，异常未被捕获导致 handler 直接抛错。需要保证用户输入/显示名等动态内容不会破坏 Markdown，且失败时可回退为纯文本。

## 1. 方案对比 (Options)
### 方案 A
- 优点: 直接移除 parse_mode，完全规避 Markdown 解析错误。
- 缺点: 命令响应丢失格式（如 code 样式），可读性下降。
- 成本: 低。

### 方案 B
- 优点: 保留 Markdown 格式，同时对动态字段做转义，并统一走容错发送逻辑。
- 缺点: 仍依赖 Markdown 规范；若上游文本本身不合法仍需回退。
- 成本: 低。

## 2. 决策 (Decision)
采用方案 B：对动态内容做 Markdown 转义，并将关键命令回复统一走 `_send_with_fallback`。

## 3. 设计与实现 (Design & Implementation)
- 新增 `_escape_markdown` 包装，统一对用户输入/ID 做 Markdown v1 转义。
- `start`/`whoami`/`user_create`/`help` 改为使用 `_send_with_fallback`，避免异常冒泡。
- `user_create` 输出对 display_name 与 user_id 做转义，避免解析错误。

## 4. 实验与效果 (Experiment & Result)
N/A：未在本地执行 Telegram 端到端验证（需可用 Bot 环境）。

## 5. 测试与优化 (Tests & Optimization)
- [ ] 单元测试: N/A（当前无相关测试框架/用例）
- [ ] 集成测试: N/A（需要 Telegram 环境）
- [ ] 手动验证: 未执行
- 结果/备注: 已通过代码路径审查确认异常路径被捕获。

## 6. 结论与收获 (Lessons)
包含用户输入的 Telegram Markdown 输出必须进行转义并具备回退通道，避免单条消息导致整个 handler 抛错。

## 7. 后续行动 (Next)
考虑补充 Telegram handler 的统一错误处理与最小手动验证流程。
