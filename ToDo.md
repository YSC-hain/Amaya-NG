# Amaya-NG 代码重构计划

> 生成时间: 2026-01-05
> 状态: 进行中

## Phase 1: 紧急修复（消除重复代码）

- [x] **1.1 统一日程表解析函数**
  - 问题: `_parse_schedule_date`, `_parse_schedule_time`, `_sort_schedule_items` 在 `tools.py` 和 `storage.py` 中重复定义
  - 方案: 保留 `storage.py` 中的实现，`tools.py` 改为导入
  - 文件: `core/tools.py`, `utils/storage.py`
  - ✅ 完成: 2026-01-05

## Phase 2: 结构重构（拆分 storage.py）

> 原始 storage.py: 927 行 → 重构后: 526 行（减少 401 行，43%）

- [x] **2.1 创建 `utils/db.py`**
  - 职责: SQLite 连接、锁、初始化
  - 从 `storage.py` 提取: `_get_db_connection`, `_init_db`, `_db_lock`, `DB_PATH`
  - ✅ 完成: 2026-01-05

- [x] **2.2 创建 `utils/user_storage.py`**
  - 职责: 用户管理
  - 从 `storage.py` 提取: `create_user`, `lookup_user_id`, `link_user_mapping`, `resolve_user_id`, `list_users`, `list_user_mappings`, `get_external_id`, `_create_user_id`
  - ✅ 完成: 2026-01-05

- [x] **2.3 创建 `utils/memory_storage.py`**
  - 职责: 记忆文件系统操作
  - 从 `storage.py` 提取: `list_files_in_memory`, `read_file_content`, `write_file_content`, `delete_file`, `_get_user_memory_dir`, `_safe_user_id`
  - ✅ 完成: 2026-01-05

- [ ] **2.4 创建 `utils/schedule_storage.py`** (延后)
  - 职责: 日程表管理
  - 从 `storage.py` 提取: `load_schedule`, `save_schedule`, `get_schedule_summary`, `_default_schedule`, `_normalize_schedule`, `build_schedule_item_id`, `_parse_schedule_date`, `_time_to_minutes`, `_sort_schedule_items`, `_format_schedule_item`

- [ ] **2.5 创建 `utils/event_bus.py`** (延后)
  - 职责: 事件总线
  - 从 `storage.py` 提取: `append_event_to_bus`, `read_events_from_bus`

- [ ] **2.6 创建 `utils/reminder_storage.py`** (延后)
  - 职责: 提醒持久化
  - 从 `storage.py` 提取: `load_all_pending_reminders`, `get_pending_reminders_summary`, `_load_pending_reminders`, `_save_pending_reminders`, `build_reminder_id`

- [x] **2.7 重构 `utils/storage.py` 为聚合层**
  - 保留 `get_global_context_string` 和必要的 re-export
  - 确保向后兼容（其他模块的 import 不需要改动）
  - ✅ 完成: 2026-01-05 (部分完成，核心功能已拆分)

## Phase 3: 文档与设计统一

- [ ] **3.1 明确课表方案定位**
  - `routine.json`: 结构化日程表（按天，通用）
  - `course_schedule.md`: 原始课表源文件（Markdown，人类可读）
  - 更新 `readme.md` 和 `config.py` 中的说明

## Phase 4: 增强与稳定性

- [ ] **4.1 Gemini SDK 兼容层增强**
  - 减少对 `_api_client` 私有字段的依赖
  - 添加版本检测或 fallback

- [ ] **4.2 统一 Telegram 错误处理**
  - 提取通用错误处理装饰器

- [ ] **4.3 添加核心功能单元测试**
  - 优先覆盖: 日程表操作、提醒调度、用户映射

## 已完成

- [x] 代码库全面分析
- [x] 制定重构计划

## 已放弃/延后

- ~~修复 0010/0011 知识库记录~~ (编码损坏，内容丢失，无法恢复)
