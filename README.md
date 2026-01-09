Amaya-NG 是一个单用户、串行处理的陪伴型规划与提醒系统。核心事实与约束请先阅读：
- `docs/FACTS.md`
- `docs/runtime/ARCHITECTURE.md`
- `docs/runtime/STATE.md`
- `docs/runtime/TOOLS.md`
- `docs/runtime/PROMPTS.md`

关于开发规范请阅读：
- `docs/dev/LLM_GUIDE.md`
- `ROADMAP.md`

## 快速开始（本地长轮询）
请先安装 `uv`：https://docs.astral.sh/uv/

```
export TELEGRAM_BOT_TOKEN="123456:ABCDEF..."
uv sync
uv run python -m amaya.bot.telegram_bot
```

## 数据目录与种子策略
- `data/` 为运行时目录，必须保持在 Git 忽略中。
- 首次启动会从 `seeds/` 复制缺失文件到 `data/`（不会覆盖已存在数据）。
- `seeds/kb/preferences.md` 内包含默认时区 `Asia/Shanghai`。

## 最小目录结构（Phase 1）
```
seeds/
  plan.json
  reminders.json
  meta.json
  kb/
    preferences.md
    goals.md
src/
  amaya/
    bot/
      telegram.py
      telegram_bot.py
    state/
      bootstrap.py
      render.py
```
