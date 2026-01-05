# AI 知识库（给 AI 使用的文档体系）

## 目标
让 AI 不再“从零思考”，而是依赖结构化记录快速理解历史决策与经验。

## 结构
- `docs/ai_knowledge_base/index.md`: 总览与入口
- `docs/ai_knowledge_base/records/`: 变更记录（严格模板）
- `docs/ai_knowledge_base/templates/record_template.md`: 记录模板
- `docs/ai_knowledge_base/AI_RECORDING_GUIDE.md`: AI 记录规范

## 工作流（固定顺序）
发现问题 -> 思考方案 -> 选择方案 -> 着手实现 -> 实验效果 -> 测试优化 -> 记录收获

## 维护规则（强制）
- 每次有“可复述的修复/决策”就新增一条记录。
- 记录完成后必须更新 `docs/ai_knowledge_base/index.md` 的“最新记录”。
- 记录用中文，遵循模板，不跳过章节（无内容写 N/A + 原因）。
- 不写入密钥、Token 或隐私内容。
