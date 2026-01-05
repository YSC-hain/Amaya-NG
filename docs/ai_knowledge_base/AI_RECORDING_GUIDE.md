# AI 记录规范（强制）

## 何时记录
- 代码、架构、配置、流程、接口等发生“可复述的修复/决策”时必须记录。
- 纯小改动可合并为一条记录，但不要跨越主题。

## 如何记录
- 严格使用模板：`docs/ai_knowledge_base/templates/record_template.md`
- 不跳过章节：无内容写 “N/A + 原因”
- 文字应可复用、可复述、可复查
- 避免主观修辞与情绪化表达
- 文件命名：`docs/ai_knowledge_base/records/0001-short-title.md`（4 位递增 ID）

## 记录后要做的事
- 更新 `docs/ai_knowledge_base/index.md` 的“最新记录”
- 若有新的约束或风险，更新 index 的“约束与约定”

## 内容禁区
- Token、密钥、账号、个人隐私
- 大段日志、原始对话、完整提示词
