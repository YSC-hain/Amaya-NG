# 0004 默认用户目录迁移与访问控制/用户绑定

- 日期: 2026-01-05
- 状态: active
- 负责人: AI
- 变更类型: feature
- 影响范围: utils/storage.py, adapters/telegram_bot.py, config.py, .env.example
- 关联: 多用户需求与访问控制要求
- 约束与风险: 访问控制默认开启，未配置允许列表时会拒绝全部访问
- 环境/版本: N/A

## 0. 问题/目标 (Context)
默认用户仍使用 `data/memory_bank/` 根目录，难以与多用户路径保持一致；同时访问控制应默认开启，并提供便捷方式创建用户与绑定 Telegram ID。

## 1. 方案对比 (Options)
### 方案 A
- 优点: 不需要迁移历史文件
- 缺点: 默认用户路径与多用户路径不一致；权限默认放行不安全
- 成本: 低

### 方案 B
- 优点: 所有用户统一使用 `data/memory_bank/<user_id>`；访问控制默认开启；提供用户创建与绑定命令
- 缺点: 需要处理旧目录文件迁移
- 成本: 中

## 2. 决策 (Decision)
采用方案 B：默认用户目录切换到子目录，并加入一次性迁移逻辑；访问控制默认启用；新增用户创建与绑定功能。

## 3. 设计与实现 (Design & Implementation)
- 存储层默认目录改为 `data/memory_bank/<user_id>`，并对旧根目录文件执行一次性迁移（冲突文件跳过并告警）。
- 增加用户管理函数：`lookup_user_id`、`create_user`、`link_user_mapping`、`list_users`、`list_user_mappings`。
- 配置新增 `REQUIRE_AUTH` 与 `ADMIN_USER_IDS`，默认开启访问控制。
- Telegram 端新增命令：`/whoami`、`/user_create`、`/user_link`，并统一未授权提示。

## 4. 实验与效果 (Experiment & Result)
N/A（未做自动化实验）

## 5. 测试与优化 (Tests & Optimization)
- [ ] 单元测试:
- [ ] 集成测试:
- [ ] 手动验证:
- 结果/备注: N/A（未执行）

## 6. 结论与收获 (Lessons)
访问控制应默认显式配置，避免“默认放行”的隐患；多用户目录统一后可简化后续维护与权限隔离。

## 7. 后续行动 (Next)
- 补充手动验证流程（创建用户、绑定 ID、触发对话）
- 如有需要，补充脚本化迁移与审计工具
