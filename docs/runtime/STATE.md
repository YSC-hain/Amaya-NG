# STATE（v0.4）- 数据结构与目录约定（单用户）

## 1. 目录结构（建议）
data/
  plan.json
  plan.md
  reminders.json
  kb/
    preferences.md
    goals.md
    projects/
      <slug>.md
  meta.json

约束：
- plan.md 只读视图；禁止作为写入源。
- plan.json 为计划唯一真相源（结构化工具修改）。
- reminders.json 为送达层真相源（由系统从 plan 派生/同步）。
- 用户时区写入 kb/preferences（默认固定值）。

---

## 2. plan.json（结构化计划：固定清单 -> 项目分组 -> 任务嵌套）
### 2.1 顶层结构
{
  "version": 1,
  "lists": [
    {
      "id": "inbox",
      "name": "Inbox",
      "groups": [
        {
          "id": "grp_amaya",
          "name": "Amaya-NG",
          "tasks": [ ... ]
        }
      ]
    }
  ]
}

### 2.2 固定清单集合（Lists）
必须至少包含：
- inbox
- nowTask
- next_action
- someday
- waiting
- routine
- checklist

### 2.3 group（项目分区）
group = {
  "id": "grp_...",
  "name": "string",
  "tasks": [ task, ... ]
}

### 2.4 task（支持嵌套；hard/soft 由 reminder 是否存在决定）
task = {
  "id": "tsk_...",
  "title": "string",
  "note": "string|null",
  "status": "todo|doing|done|blocked",
  "priority": "low|normal|high|critical",

  "planning": {
    "schedule": {
      "intent": "unscheduled|date_only|time_window|exact_time",
      "date": "YYYY-MM-DD|null",
      "time": "HH:MM|null",
      "window": { "start":"HH:MM", "end":"HH:MM" } | null
    },

    "reminder": {
      "at": "ISO-8601 (user timezone semantics)",
      "text_override": "string|null"
    } | null,

    "review": {
      "next_review_at": "ISO-8601|null",
      "reason": "string|null"
    }
  },

  "estimate_minutes": 30,
  "tags": ["tag1","tag2"],
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",

  "children": [ task, ... ]
}

语义：
- 软性规划（soft）：planning.reminder = null；schedule 可为 date_only（只按天）
- 硬性规划（hard）：planning.reminder != null；系统需确保送达（派生 reminders.json）
- next_action 默认 priority=low（可被显式修改）

---

## 3. plan.md（只读渲染视图）
- 由 plan.json 渲染生成，不可直接编辑。
- 渲染结构建议：
  - 一级标题：清单（List）
  - 二级标题：分组（Group / 项目）
  - 任务列表：包含状态/优先级/时间信息的简写

---

## 4. reminders.json（系统托管提醒：允许远期）
### 4.1 顶层结构
{
  "version": 1,
  "items": [
    {
      "id": "rem_...",
      "run_at": "ISO-8601 (user timezone semantics or normalized)",
      "priority": "low|normal|high|critical",
      "source": { "type": "plan_task", "task_id": "tsk_..." },
      "status": "scheduled|sent|acknowledged|canceled|failed",
      "created_at": "ISO-8601",
      "updated_at": "ISO-8601",
      "delivery": {
        "attempts": 0,
        "last_attempt_at": "ISO-8601|null"
      }
    }
  ]
}

说明：
- reminders.json 由系统从 plan.json 中 planning.reminder != null 的任务派生/同步。
- priority 继承自 task.priority，用于后续多渠道/ask 策略。

---

## 5. meta.json（运行元信息）
最小建议字段：
{
  "version": 1,
  "last_plan_review_at": "ISO-8601|null",
  "last_reminder_sync_at": "ISO-8601|null"
}

---

## 6. kb/（知识库：模板化）
### 6.1 preferences.md（含时区）
最小包含：
- timezone: Asia/Shanghai
- reminder_style: 用户偏好（简短/温和/强提醒等）
- work_hours / sleep / do_not_disturb（如需要）

### 6.2 goals.md
记录长期/近期目标、里程碑、最近确认时间。

### 6.3 projects/<slug>.md（项目档案）
项目档案属于 KB，不替代 plan：
- 简介/动机
- 当前状态
- 关键资源
- 约束与偏好
- 下一步摘要（真正任务仍落 plan）
