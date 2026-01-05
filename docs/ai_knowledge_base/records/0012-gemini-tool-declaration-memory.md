# 0012 修复 Gemini 工具声明与记忆落盘排查

- 日期: 2026-01-05
- 状态: active
- 负责人: AI
- 变更类型: bugfix
- 影响范围: core/llm/gemini.py, readme.md
- 关联: N/A
- 约束与风险: N/A
- 环境/版本: google-genai SDK (现有 venv 版本)

## 0. 问题/目标 (Context)
Gemini 工具声明在当前 SDK 版本中要求传入 client。现有实现用位置参数调用导致 `FunctionDeclaration.from_callable` 报错，工具未注册，出现频繁工具调用失败。同时记忆文件依赖 `save_memory` 工具调用，工具失效时会表现为 `data/memory_bank/<user_id>/` 为空。目标是恢复工具声明并澄清记忆落盘条件与路径。

## 1. 方案对比 (Options)
### 方案 A
- 优点: 不改代码，依赖降级或外部修复
- 缺点: 工具调用继续失败，记忆文件不可用
- 成本: 需要锁版本并回滚依赖

### 方案 B
- 优点: 兼容 SDK 签名变化，工具声明可用；文档明确记忆落盘路径与触发条件
- 缺点: 引入对 SDK 私有字段 `_api_client` 的使用
- 成本: 少量代码和文档调整

## 2. 决策 (Decision)
选择方案 B，新增工具声明的版本兼容处理，并更新说明。

## 3. 设计与实现 (Design & Implementation)
- `core/llm/gemini.py`: 新增 `_build_function_declaration`，根据 SDK 签名传入 `client`（`self.client._api_client`）或回退到旧签名。
- `readme.md`: 补充 `save_memory` 触发与 `data/memory_bank/<user_id>/` 路径说明，避免误判“记忆系统无输出”。

## 4. 实验与效果 (Experiment & Result)
N/A（未在本地发起真实 Gemini 调用，仅做静态修复）。

## 5. 测试与优化 (Tests & Optimization)
- [ ] 单元测试: N/A（未覆盖工具声明构建）
- [ ] 集成测试: N/A
- [ ] 手动验证: N/A
- 结果/备注: 待使用 Gemini 真实调用验证工具注册与 `save_memory` 落盘。

## 6. 结论与收获 (Lessons)
SDK 工具声明接口可能变更，应通过签名检测或兼容层避免整体工具失效；记忆落盘依赖工具调用成功，文档需明确触发条件与路径。

## 7. 后续行动 (Next)
- 补充 Gemini 工具注册的集成验证日志或自检脚本。
- 进行一次 `save_memory` 调用验证落盘路径与权限。
