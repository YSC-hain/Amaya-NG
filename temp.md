# AI Knowledge Base Draft (temp)

## Goals
- Give the AI a compact, structured, evolving memory of what changed and why.
- Avoid "thinking from scratch" by recording context, decisions, and lessons.
- Keep it easy to scan and safe to share (no secrets, no tokens).

## What I learned from this repo (quick scan)
- Core idea: file-based long-term memory, robust reminders, and multi-LLM support.
- Existing docs already explain memory practices and LLM call flow.
- There is a `data/memory_bank/` with routine/plan/goals, so "user memory" exists.

## Proposed knowledge base layout (options)
Option A: `docs/ai_kb/`
- `index.md` (front page: project summary, current focus, latest 5 records)
- `records/` (chronological CODDRL entries)
- `templates/` (record template + short checklist)

Option B: `docs/ai/`
- `README.md` (front page)
- `records/`
- `templates/`

Option C: `data/ai_kb/` (if you want it to be "runtime memory")

## Record format (CODDRL)
Title: short, concrete, 1 line
- Context: what problem/goal triggered the change?
- Options: 2-3 considered paths, with tradeoffs.
- Decision: what was chosen and why.
- Design: important details of the solution (APIs, files, data flow).
- Result: expected outcome or observed behavior.
- Lessons: what to repeat/avoid next time.

## Lightweight workflow
- Every meaningful change adds a new record.
- Update `index.md` with:
  - Current focus (1-3 items)
  - Recent changes (links to latest records)
  - Known constraints (1-5 bullets)
- Add "tests/status" in each record (run? not run? reason).

## Open questions for you
1. Where should the AI knowledge base live? `docs/` vs `data/` vs root.
2. Chinese or English in the records?
3. Do you want strict templates or a flexible format?
4. Should we backfill old changes, or start fresh from now?
5. Do you want separate logs for "decisions" vs "experiments"?
