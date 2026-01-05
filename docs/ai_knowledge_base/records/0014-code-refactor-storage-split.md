# 0014 代码重构：消除重复函数与拆分 storage.py

- 日期: 2026-01-05
- 状态: active
- 负责人: AI
- 变更类型: refactor
- 影响范围: utils/storage.py, utils/db.py, utils/user_storage.py, utils/memory_storage.py, core/tools.py
- 关联: 全面代码分析后的技术债清理
- 约束与风险: 需确保向后兼容，其他模块的 import 不需修改
- 环境/版本: N/A

## 0. 问题/目标 (Context)

### 问题分析
1. **重复代码**: `_parse_schedule_date`, `_parse_schedule_time`, `_sort_schedule_items` 在 `tools.py` 和 `storage.py` 中重复定义
2. **storage.py 过大**: 927 行代码承担了过多职责（用户管理、文件系统、日程表、事件总线、提醒等）
3. **知识库记录 0010/0011 编码损坏**: 决定放弃修复

### 目标
- 消除重复代码
- 拆分 storage.py 为多个职责单一的模块
- 保持向后兼容

## 1. 方案对比 (Options)

### 方案 A：仅消除重复
- 优点: 改动小，风险低
- 缺点: 不解决 storage.py 过大问题
- 成本: 低

### 方案 B：完全重构
- 优点: 彻底解决问题，代码结构清晰
- 缺点: 工作量大，需要修改所有 import
- 成本: 高

### 方案 C：增量重构 + re-export
- 优点: 逐步拆分，通过 re-export 保持向后兼容
- 缺点: 过渡期存在两层间接调用
- 成本: 中

## 2. 决策 (Decision)
选择方案 C：增量重构 + re-export
- 新建独立模块
- storage.py 从新模块导入并 re-export
- 其他模块的 import 语句无需修改

## 3. 设计与实现 (Design & Implementation)

### 3.1 消除重复函数
- `tools.py` 中删除 `_parse_schedule_date`, `_parse_schedule_time`, `_sort_schedule_items`
- 改为从 `storage.py` 导入
- `storage.py` 中添加别名 `_parse_schedule_time = _time_to_minutes`

### 3.2 新建模块

| 模块 | 职责 | 行数 |
|------|------|------|
| `utils/db.py` | SQLite 连接、锁、表初始化 | ~110 |
| `utils/user_storage.py` | 用户创建、查询、平台映射 | ~230 |
| `utils/memory_storage.py` | 记忆文件系统读写 | ~90 |

### 3.3 storage.py 重构
- 从新模块导入并 re-export
- 删除已迁移的函数定义
- 保留日程表、事件总线、提醒、上下文聚合等功能（后续迭代拆分）

## 4. 实验与效果 (Experiment & Result)

| 指标 | 重构前 | 重构后 | 变化 |
|------|--------|--------|------|
| storage.py 行数 | 927 | 526 | -43% |
| 重复函数 | 3 | 0 | 消除 |
| 模块数 | 1 | 4 | +3 |

## 5. 测试与优化 (Tests & Optimization)
- [ ] 单元测试: N/A（无现有测试）
- [ ] 集成测试: N/A
- [x] 手动验证: 语法检查通过，无 import 错误
- 结果/备注: 需要实际运行验证功能正常

## 6. 结论与收获 (Lessons)

1. **增量重构优于大爆炸**: 通过 re-export 保持向后兼容，降低风险
2. **职责单一原则**: 大文件拆分后更易维护和测试
3. **别名处理命名不一致**: `_time_to_minutes` 和 `_parse_schedule_time` 实际相同，通过别名统一

## 7. 后续行动 (Next)

- [ ] 继续拆分: `schedule_storage.py`, `event_bus.py`, `reminder_storage.py`
- [ ] 添加单元测试覆盖核心函数
- [ ] 实际运行验证重构后功能正常
