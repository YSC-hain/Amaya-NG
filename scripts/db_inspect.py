#!/usr/bin/env python
"""
Inspect Amaya SQLite database for quick debugging.

Examples:
  python scripts/db_inspect.py
  python scripts/db_inspect.py --table sys_events --limit 20
  python scripts/db_inspect.py --table sys_events --where "status='pending'"
"""
import argparse
import json
import os
import sqlite3


def _get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def _table_counts(conn: sqlite3.Connection, tables: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts


def _dump_table(conn: sqlite3.Connection, table: str, limit: int, where: str | None) -> list[dict]:
    query = f"SELECT * FROM {table}"
    if where:
        query += f" WHERE {where}"
    query += " ORDER BY 1 DESC"
    query += " LIMIT ?"
    rows = conn.execute(query, (limit,)).fetchall()
    return [dict(r) for r in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Amaya SQLite database.")
    parser.add_argument(
        "--db-path",
        default=os.getenv("AMAYA_DB_PATH", os.path.join("data", "amaya.db")),
        help="Path to SQLite DB"
    )
    parser.add_argument("--table", help="Table name to dump")
    parser.add_argument("--limit", type=int, default=50, help="Rows to show")
    parser.add_argument("--where", help="Optional SQL WHERE clause (advanced)")
    args = parser.parse_args()

    with _get_conn(args.db_path) as conn:
        tables = _list_tables(conn)
        if not args.table:
            summary = {
                "db_path": args.db_path,
                "tables": tables,
                "counts": _table_counts(conn, tables)
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return

        if args.table not in tables:
            raise SystemExit(f"Unknown table: {args.table}. Available: {', '.join(tables)}")

        data = _dump_table(conn, args.table, args.limit, args.where)
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
