"""
Run every SQLite query in sql/sqlite/ against data/hospital_operations.db and
save the result sets to results/<query>.csv.

Run:  python scripts/run_queries.py
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "hospital_operations.db"
OUT = ROOT / "results"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    for path in sorted((ROOT / "sql" / "sqlite").glob("*.sql")):
        t0 = time.perf_counter()
        df = pd.read_sql_query(path.read_text(), con)
        df.to_csv(OUT / f"{path.stem}.csv", index=False)
        print(f"{path.stem:<50} {len(df):>7,} rows  {time.perf_counter() - t0:5.1f}s")
    con.close()


if __name__ == "__main__":
    main()
