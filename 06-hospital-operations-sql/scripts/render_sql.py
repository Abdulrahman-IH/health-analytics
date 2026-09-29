"""
Render the dialect-neutral query templates in sql/templates/ into
sql/sqlite/*.sql and sql/postgres/*.sql.

The analytical logic (CTEs, window functions, joins) is identical in both
engines; only date/time functions differ. Templates mark those spots with a
handful of macros, so each query is written once and both dialects stay in
sync. scripts/verify_postgres.py then proves the two renderings return the
same numbers.

Macros (arguments may nest):
  @DATE(ts)            calendar date of a timestamp
  @LIT(2025-01-01)     typed date literal
  @ADD_DAYS(d, n)      date + n days (n integer literal)
  @DAYS(a, b)          fractional days from a to b
  @MINUTES(a, b)       fractional minutes from a to b
  @DATE_KEY(d)         integer day number (for gaps-and-islands arithmetic)
  @DOW(ts)             day of week, 0 = Sunday … 6 = Saturday
  @HOUR(ts)            hour of day 0-23
  @MONTH(ts)           'YYYY-MM' text
  @WEEK(ts)            Monday that starts the ISO week, as a date

Run:  python scripts/render_sql.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "sql" / "templates"

DIALECTS = {
    "sqlite": {
        "DATE": lambda x: f"date({x})",
        "LIT": lambda x: f"'{x}'",
        "ADD_DAYS": lambda d, n: f"date({d}, '+{n} day')",
        # strftime('%s') gives exact integer epoch seconds; julianday() arithmetic
        # carries float error that flips boundary tests such as "<= 240 minutes"
        "DAYS": lambda a, b: f"((strftime('%s', {b}) - strftime('%s', {a})) / 86400.0)",
        "MINUTES": lambda a, b: f"(strftime('%s', {b}) - strftime('%s', {a})) / 60.0",
        "DATE_KEY": lambda d: f"CAST(julianday({d}) AS INTEGER)",
        "DOW": lambda x: f"CAST(strftime('%w', {x}) AS INTEGER)",
        "HOUR": lambda x: f"CAST(strftime('%H', {x}) AS INTEGER)",
        "MONTH": lambda x: f"strftime('%Y-%m', {x})",
        "WEEK": lambda x: f"date({x}, '-6 days', 'weekday 1')",
    },
    "postgres": {
        "DATE": lambda x: f"CAST({x} AS DATE)",
        "LIT": lambda x: f"DATE '{x}'",
        "ADD_DAYS": lambda d, n: f"({d} + {n})",
        "DAYS": lambda a, b: f"(EXTRACT(EPOCH FROM ({b} - {a})) / 86400.0)",
        "MINUTES": lambda a, b: f"EXTRACT(EPOCH FROM ({b} - {a})) / 60.0",
        "DATE_KEY": lambda d: f"({d} - DATE '2000-01-01')",
        "DOW": lambda x: f"CAST(EXTRACT(DOW FROM {x}) AS INTEGER)",
        "HOUR": lambda x: f"CAST(EXTRACT(HOUR FROM {x}) AS INTEGER)",
        "MONTH": lambda x: f"to_char({x}, 'YYYY-MM')",
        "WEEK": lambda x: f"CAST(date_trunc('week', {x}) AS DATE)",
    },
}

MACRO = re.compile(r"@([A-Z_]+)\(")


def _split_args(s: str) -> list[str]:
    args, depth, cur = [], 0, ""
    for ch in s:
        if ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
            continue
        depth += ch == "("
        depth -= ch == ")"
        cur += ch
    args.append(cur.strip())
    return args


def render(sql: str, dialect: str) -> str:
    funcs = DIALECTS[dialect]
    while (m := MACRO.search(sql)) is not None:
        name, start = m.group(1), m.end()
        depth, i = 1, start
        while depth:
            depth += {"(": 1, ")": -1}.get(sql[i], 0)
            i += 1
        args = [render(a, dialect) for a in _split_args(sql[start:i - 1])]
        sql = sql[:m.start()] + funcs[name](*args) + sql[i:]
    return sql


def main() -> None:
    for tpl in sorted(TEMPLATES.glob("*.sql")):
        body = tpl.read_text()
        for dialect in DIALECTS:
            out = ROOT / "sql" / dialect / tpl.name
            header = f"-- Dialect: {'SQLite 3.25+' if dialect == 'sqlite' else 'PostgreSQL 13+'}  " \
                     f"(generated from sql/templates/{tpl.name} by scripts/render_sql.py)\n"
            out.write_text(header + render(body, dialect))
        print(f"rendered {tpl.name}")


if __name__ == "__main__":
    main()
