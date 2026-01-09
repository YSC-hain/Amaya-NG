# LLM_GUIDE（v0.4）- 给 Builder LLM 的硬规则（交互式重建）

## 0. 两种 LLM，禁止混淆
- Runtime LLM：运行系统调用的模型
- Builder LLM：写代码/重构/文档的模型（你）

---

## 1. Builder LLM 的工作方式（必须遵守）
用户要求：任何不确定细节必须先询问；重建采用交互式流程；先变更提案再实现；允许分阶段大重构并由用户审核。

因此你必须：
- 先输出“变更提案”（Proposal），用户审核后才能写代码
- 大改动必须拆分阶段（Phase），每阶段有验收标准
- 任何不确定点必须列出问题等待用户回答

---

## 2. Builder LLM 的优先级
1) 可控可验收（小步、可回滚）
2) 文档先行（FACTS/STATE/TOOLS/PROMPTS 与 ADR）
3) 再实现代码重构
4) 最后才是性能/优雅/抽象

---

## 3. 不可破坏约束（Invariants）
以下任一被破坏都算失败：
1) plan.md 只读视图：所有写入通过 plan.json 的结构化工具
2) 提醒从属于规划：reminders.json 由系统从 plan 派生/同步
3) 工具诚实性：未落盘不能声称已完成
4) 单用户：不得偷偷引入 user_id 体系（除非 ADR+用户明确同意）
5) 时区规则：reminder.at 使用用户时区；默认固定写入 preferences

---

## 4. 强制输出模板
### 4.1 变更提案模板（必须先给）
- 目标：
- Non-goals：
- 影响范围（文件/模块）：
- 风险点：
- 验证方法：
- 回滚方式：
- 待确认问题清单：

### 4.2 分阶段模板（大重构必须）
- Phase 1：目标/验收标准
- Phase 2：目标/验收标准
- ...

---

## 5. 必读文档清单（每次动手前）
- docs/FACTS.md
- docs/runtime/ARCHITECTURE.md
- docs/runtime/STATE.md
- docs/runtime/TOOLS.md
- docs/runtime/PROMPTS.md
- docs/adr/*（如存在）
