"""
Load the SQLite database into PostgreSQL using sql/schema.sql.

Uses the psql client, so no Python driver is needed. Connection details come
from the standard libpq environment variables (PGHOST, PGPORT, PGUSER,
PGPASSWORD); the target database must already exist.

Run:  createdb hospital_operations
      python scripts/load_postgres.py --dbname hospital_operations
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "hospital_operations.db"
TABLES = ["hospitals", "departments", "bed_capacity", "patients",
          "admissions", "er_visits", "staffing_shifts"]  # FK order


def psql(dbname: str, *args: str) -> None:
    subprocess.run(["psql", "-d", dbname, "-v", "ON_ERROR_STOP=1", "-q", "-c", "SET client_min_messages = warning", *args], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dbname", default="hospital_operations")
    dbname = ap.parse_args().dbname

    psql(dbname, "-f", str(ROOT / "sql" / "schema.sql"))
    con = sqlite3.connect(DB)
    with tempfile.TemporaryDirectory() as tmp:
        for table in TABLES:
            df = pd.read_sql_query(f"SELECT * FROM {table}", con)
            # nullable integer FK columns must not be written as floats (e.g. 12.0)
            for col in df.columns:
                if df[col].dtype == float and df[col].dropna().mod(1).eq(0).all():
                    df[col] = df[col].astype("Int64")
            path = Path(tmp) / f"{table}.csv"
            df.to_csv(path, index=False)
            psql(dbname, "-c", f"\\copy {table} FROM '{path}' WITH (FORMAT csv, HEADER true)")
            print(f"loaded {table:<16} {len(df):>8,} rows")
    psql(dbname, "-c", "ANALYZE")


if __name__ == "__main__":
    main()
