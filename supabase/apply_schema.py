"""Apply supabase/schema.sql to the database in SUPABASE_DB_URL (.env).

Usage: venv\\Scripts\\python.exe supabase\\apply_schema.py
"""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def main():
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL is not set in .env")
    sql = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(url, connect_timeout=20) as conn:
        conn.execute(sql)
        rows = conn.execute(
            """select c.relname, c.relrowsecurity
               from pg_class c join pg_namespace n on n.oid = c.relnamespace
               where n.nspname = 'public' and c.relkind = 'r' order by 1"""
        ).fetchall()
    for name, rls in rows:
        print(f"  {name:<15} rls={'on' if rls else 'OFF'}")


if __name__ == "__main__":
    main()
