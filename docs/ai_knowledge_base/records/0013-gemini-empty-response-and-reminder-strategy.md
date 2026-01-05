# 0013 修复 Gemini 工具调用后空响应与远期提醒策略优化

- 日期: 2026-01-05
- 状态: active
- 负责人: AI
- 变更类型: bugfix
- 影响范围: core/llm/gemini.py, config.py
- 关联: 0011, 0012（Gemini 工具调用相关修复）
- 约束与风险: 工具摘要作为降级回复可能不够自然，但优于返回错误
- 环境/版本: google-genai SDK, gemini-2.5-pro-thinking

## 0. 问题/目标 (Context)

### 问题 1：空响应错误
用户发送寒假安排通知后，Amaya 成功创建了两个 `schedule_reminder`，但最终返回了错误：
```
API 调用失败，请稍后重试。错误: received empty response from Gemini: no meaningful content in candidates
```

根因分析：
- 工具调用（`schedule_reminder`）执行成功并返回结果
- 将 `function_response` 发回 Gemini 后，Gemini thinking model 可能只生成 `thought` 部分而无可见文本
- Google SDK 检测到 candidates 中没有有意义内容，抛出 `APIError`
- 当前代码将此错误直接透传给用户，导致用户看到错误信息而非工具执行结果

### 问题 2：远期提醒策略不当
用户消息中提到"1月7日17:00前提交材料"和"1月9日前办理线上手续"，LLM 直接创建了两个远期提醒（距今 2-4 天）。这种做法存在问题：
- 计划易变，远期提醒容易失效
- 提醒堆积会造成混乱
- 应使用 `plan.md` 记录待办，通过日程表 `routine.json` 做日期备忘

## 1. 方案对比 (Options)

### 方案 A：忽略空响应错误
- 优点: 简单
- 缺点: 用户看不到任何反馈，不知道工具是否成功
- 成本: 低

### 方案 B：捕获空响应错误，使用工具摘要作为降级回复
- 优点: 用户能看到工具执行结果的摘要，体验完整
- 缺点: 摘要可能不如 LLM 生成的回复自然
- 成本: 中等（需要实现工具摘要生成逻辑）

### 方案 C：仅优化提示词
- 优点: 不改代码
- 缺点: 无法解决空响应 bug
- 成本: 低

## 2. 决策 (Decision)
采用方案 B + 提示词优化：
1. 在 `gemini.py` 中捕获工具响应后的空响应错误，使用工具执行摘要作为降级回复
2. 在 `config.py` 的系统提示词中明确远期提醒策略：超过 24 小时的任务写入 `plan.md`

## 3. 设计与实现 (Design & Implementation)

### 3.1 空响应处理 (`core/llm/gemini.py`)
新增 `_build_tool_summary()` 函数，根据工具调用记录生成简洁的摘要回复：
```python
def _build_tool_summary(tool_trace: list[dict]) -> str:
    # 遍历成功的工具调用，生成友好摘要
    # schedule_reminder -> "✓ 提醒已设置"
    # save_memory -> "✓ 已保存到文件"
    # add_schedule_item -> "✓ 日程已添加"
    ...
```

在发送 `function_response` 后捕获空响应错误：
```python
try:
    response = chat_session.send_message(response_parts)
except genai.errors.APIError as tool_response_error:
    if "empty response" in str(tool_response_error) or "no meaningful content" in str(tool_response_error):
        tool_summary = _build_tool_summary(tool_call_trace)
        if tool_summary:
            response_text = tool_summary
            break
    raise
```

### 3.2 提示词优化 (`config.py`)
在 `### Tools` 部分明确 reminder 使用规范：
- **仅限硬性时间点**: Reminder 只用于有明确截止时间的紧急任务
- **禁止远期提醒**: 超过 24 小时的任务应写入 `plan.md`
- 典型场景示例

新增 `### PROTOCOL: NOTIFICATION & PLANNING` 章节，区分：
- **硬性时间任务** (使用 reminder): 24 小时以内、有明确截止时间
- **软性规划任务** (写入 plan.md): 无明确时间或超过 24 小时

## 4. 实验与效果 (Experiment & Result)
N/A（待实际对话测试验证）

预期效果：
1. 工具调用成功后即使 Gemini 返回空响应，用户也能看到工具执行摘要
2. LLM 遵循新策略，将远期任务写入 `plan.md` 而非创建 reminder

## 5. 测试与优化 (Tests & Optimization)
- [ ] 单元测试: N/A
- [ ] 集成测试: N/A
- [ ] 手动验证: 需要使用类似的寒假通知消息测试
- 结果/备注: 待测试

## 6. 结论与收获 (Lessons)
1. **Thinking Model 的特殊性**: Gemini thinking model 在工具调用后可能只产生内部思考而无可见输出，SDK 会抛出空响应错误。需要特殊处理这种情况。
2. **降级策略的重要性**: 当 LLM 无法生成正常回复时，使用工具执行摘要作为降级回复优于直接报错。
3. **提醒 vs 规划的边界**: 提醒适合硬性时间点的短期任务；长期/弹性任务应使用文件记录，避免提醒堆积和失效。

## 7. 后续行动 (Next)
- 测试修复后的空响应处理逻辑
- 观察 LLM 是否遵循新的远期任务处理策略
- 考虑增加工具摘要的自然语言润色（可选）
