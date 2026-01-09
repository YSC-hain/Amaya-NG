from __future__ import annotations
from amaya.config import get_telegram_bot_token
from amaya.state.bootstrap import ensure_runtime_data
from amaya.bot.telegram import TelegramAdapter
from amaya.state.render import render_plan_md
from pathlib import Path

async def handle_text(text: str) -> str:
    return text

def main() -> None:
    try:
        token = get_telegram_bot_token()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    ensure_runtime_data()

    # render plan.md once at startup (Phase 1)
    root = Path(__file__).resolve().parents[3]
    plan_json = root / "data" / "plan.json"
    plan_md = root / "data" / "plan.md"
    render_plan_md(plan_json, plan_md)

    adapter = TelegramAdapter(token=token, handle_text=handle_text)
    adapter.run_polling()

if __name__ == "__main__":
    main()
