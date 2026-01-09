from __future__ import annotations
import json
from pathlib import Path

def render_plan_md(plan_json_path: Path, plan_md_path: Path) -> None:
    plan = json.loads(plan_json_path.read_text(encoding="utf-8"))
    lines: list[str] = ["# Plan\n"]
    for lst in plan.get("lists", []):
        lines.append(f"## {lst.get('name', lst.get('id'))}\n")
        for grp in lst.get("groups", []) or []:
            lines.append(f"### {grp.get('name', grp.get('id'))}\n")
            tasks = grp.get("tasks", []) or []
            for t in tasks:
                lines.append(f"- [{t.get('status','todo')}] {t.get('title','(untitled)')}\n")
        lines.append("\n")
    plan_md_path.write_text("".join(lines), encoding="utf-8")
