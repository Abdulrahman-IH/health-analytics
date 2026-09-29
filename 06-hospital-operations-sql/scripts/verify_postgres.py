"""
Cross-check the two SQL dialects: run every query in sql/postgres/ against a
PostgreSQL copy of the data (see load_postgres.py) and compare the result set
with the SQLite output of the matching query in sql/sqlite/.

Run:  python scripts/verify_postgres.py --dbname hospital_operations
"""

from __future__ import annotations

import argparse
import io
import sqlite3
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def run_pg(dbname: str, sql: str) -> pd.DataFrame:
    out = subprocess.run(["psql", "-d", dbname, "-v", "ON_ERROR_STOP=1", "--csv", "-c", sql],
                         check=True, capture_output=True, text=True).stdout
    return pd.read_csv(io.StringIO(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dbname", default="hospital_operations")
    dbname = ap.parse_args().dbname
    con = sqlite3.connect(ROOT / "data" / "hospital_operations.db")
    failures = 0
    for pg_path in sorted((ROOT / "sql" / "postgres").glob("*.sql")):
        lite = pd.read_sql_query((ROOT / "sql" / "sqlite" / pg_path.name).read_text(), con)
        try:
            pg = run_pg(dbname, pg_path.read_text())
        except subprocess.CalledProcessError as exc:
            print(f"FAIL {pg_path.stem}: {exc.stderr.strip()}")
            failures += 1
            continue
        ok = list(lite.columns) == list(pg.columns) and len(lite) == len(pg)
        if ok:
            for col in lite.columns:
                a, b = lite[col], pg[col]
                if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
                    # values are ROUNDed in SQL, and a float (SQLite) vs exact numeric
                    # (PostgreSQL) half-way case can differ by one unit in the last place
                    decimals = b.dropna().astype(str).str.partition(".")[2].str.len().max()
                    atol = 1.01 * 10.0 ** -(decimals or 0)
                    ok &= bool(np.allclose(a.astype(float), b.astype(float), atol=atol, rtol=0, equal_nan=True))
                else:
                    ok &= a.astype(str).str.replace(r"\.0$", "", regex=True).equals(
                          b.astype(str).str.replace(r"\.0$", "", regex=True))
                if not ok:
                    print(f"   mismatch in column {col}")
                    break
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {pg_path.stem:<50} {len(pg):>7,} rows")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
