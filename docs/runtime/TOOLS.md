# TOOLS（v0.4）- 结构化计划工具 + 系统派生提醒（串行）

## 0. 工具调用总规则（Runtime LLM 必须遵守）
- 禁止直接写 plan.md；只能用 plan 工具修改 plan.json，并由系统渲染 plan.md。
- “提醒”不由 LLM 直接维护 reminders.json；LLM 通过设置 task 的 planning.reminder 驱动系统派生/同步。
- 未执行工具成功落盘前，不得声称“已保存/已更新/已安排好”。

---

## 1. plan 工具（结构化操作）
### 1.1 plan.get(mode)
- mode: full|summary

### 1.2 plan.ensure_list(list_id, display_name)
- list_id 必须属于固定集合：
  inbox | nowTask | next_action | someday | waiting | routine | checklist

### 1.3 plan.ensure_group(list_id, group_name)
- 若分组不存在则创建

### 1.4 plan.add_task(list_id, group_id, task_payload)
- 系统补齐 id/created_at/updated_at
- 若 list_id=next_action 且未指定 priority，则系统默认 priority=low

### 1.5 plan.update_task(task_id, patch_payload)
允许修改：
- title/note/status/priority/estimate_minutes/tags

### 1.6 plan.set_schedule(task_id, schedule_payload)
- intent ∈ unscheduled|date_only|time_window|exact_time
- date_only：仅允许 date，不允许 time/window
- exact_time：必须提供 date + time

### 1.7 plan.set_reminder(task_id, reminder_payload)
- reminder_payload.at：ISO-8601（用户时区语义），必须是未来时间
- reminder_payload.text_override：仅在用户明确要求固定提醒内容时使用（可为空）
- 规则：若该任务当前 schedule.intent=date_only 且没有明确 time，则不得 set_reminder；应改为软性 + 设置 next_review。

### 1.8 plan.clear_reminder(task_id)
- 清除 reminder（任务回到软性规划）

### 1.9 plan.set_review(task_id, next_review_at, reason|null)

### 1.10 plan.move_task(task_id, target_list_id, target_group_id, parent_task_id|null, position|null)

### 1.11 plan.complete_task(task_id)

### 1.12 plan.render_md()

---

## 2. reminder 派生/同步（系统内部，不暴露给 Runtime LLM）
### 2.1 reminder.sync_from_plan()
- 对每个 task（planning.reminder != null）确保存在对应 reminders.json 项
- 将 reminders.run_at = task.planning.reminder.at
- priority 继承 task.priority
- source 固定为 { type:"plan_task", task_id:"..." }
- 当 task 完成或 clear_reminder 时，取消/移除对应 reminders 项（实现可选择标记 canceled 或删除）

---

## 3. kb 工具（模板化）
### 3.1 kb.read(entry)
- entry: preferences | goals | projects/<slug>

### 3.2 kb.upsert(entry, content, mode)
- mode: replace | merge
- merge 由系统按模板合并，禁止 Runtime LLM 自由破坏结构

### 3.3 kb.list_projects()
- 返回 projects 下的条目列表（slug, title, updated_at）

### 3.4 kb.create_project(slug, title, initial_content)
- 创建 projects/<slug>.md（写入模板头）
