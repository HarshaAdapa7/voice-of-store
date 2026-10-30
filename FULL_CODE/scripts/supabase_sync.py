#!/usr/bin/env python3
"""Supabase database management and synchronization CLI tool.

Usage:
    python FULL_CODE/scripts/supabase_sync.py --check
    python FULL_CODE/scripts/supabase_sync.py --sql
    python FULL_CODE/scripts/supabase_sync.py --migrate
    python FULL_CODE/scripts/supabase_sync.py --seed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add src to python path
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from voice_of_store.db import DatabaseError, get_db  # noqa: E402


def check_status() -> int:
    """Check connectivity to Supabase and report current status."""
    db = get_db()
    status = db.check_health()
    print("=== Supabase Database Status ===")
    print(f"Configured:      {status['configured']}")
    print(f"Project URL:     {status['url'] or 'Not configured'}")
    print(f"Connection Mode: {status['mode']}")
    print(f"Connected:       {status['connected']}")
    print(f"DB Password:     {'Provided' if status['has_pg_pass'] else 'Pending (will give later)'}")
    print(f"Status Message:  {status['message']}")
    if status["tables"]:
        print(f"Existing Tables: {', '.join(status['tables'])}")
    return 0 if status["connected"] or status["configured"] else 1


def print_sql_schema() -> int:
    """Print the SQL migration schema."""
    schema_path = Path(__file__).resolve().parent / "supabase_schema.sql"
    if not schema_path.is_file():
        print(f"Schema file not found at {schema_path}", file=sys.stderr)
        return 1
    print(schema_path.read_text(encoding="utf-8"))
    return 0


def run_migration() -> int:
    """Execute the SQL migration schema against PostgreSQL if password configured."""
    db = get_db()
    if not db.config.has_db_password:
        print("Notice: Direct PostgreSQL password has not been provided yet.", file=sys.stderr)
        print("To run migrations directly, set SUPABASE_DB_PASSWORD in .env.", file=sys.stderr)
        print("Alternatively, copy FULL_CODE/scripts/supabase_schema.sql into the Supabase SQL Editor.", file=sys.stderr)
        return 2

    schema_path = Path(__file__).resolve().parent / "supabase_schema.sql"
    if not schema_path.is_file():
        print(f"Schema file not found at {schema_path}", file=sys.stderr)
        return 1

    sql = schema_path.read_text(encoding="utf-8")
    try:
        db.execute_schema_migration(sql)
        print("Schema migration completed successfully!")
        return 0
    except DatabaseError as exc:
        print(f"Migration error: {exc}", file=sys.stderr)
        print(
            "\nTip: If direct PostgreSQL connection fails, you can run migrations instantly via\n"
            "Supabase Dashboard -> SQL Editor: copy FULL_CODE/scripts/supabase_schema.sql and execute.",
            file=sys.stderr,
        )
        return 1


def seed_data(submission_dir: Path | None = None) -> int:
    """Seed Supabase tables with submission outputs if available."""
    db = get_db()
    if not db.config.is_configured:
        print("Supabase credentials not configured in .env", file=sys.stderr)
        return 1

    sub_dir = submission_dir or (Path(__file__).resolve().parents[2] / "submission")
    flags_csv = sub_dir / "R5_emerging_flags.csv"

    if not flags_csv.is_file():
        print(f"Flags file not found at {flags_csv}", file=sys.stderr)
        return 1

    try:
        import pandas as pd

        df = pd.read_csv(flags_csv)
        client = db.get_client()
        records = []
        for _, row in df.iterrows():
            ev = str(row.get("evidence_feedback_ids", "")).split(";") if pd.notna(row.get("evidence_feedback_ids")) else []
            records.append(
                {
                    "as_of_week_start": str(row["as_of_week_start"]),
                    "store_id": str(row["store_id"]),
                    "issue_type_id": str(row["issue_type_id"]),
                    "confidence": float(row["confidence"]),
                    "evidence_feedback_ids": ev,
                }
            )

        if records:
            client.table("emerging_flags").insert(records).execute()
            print(f"Seeded {len(records)} emerging flags into Supabase.")
        return 0
    except Exception as exc:
        print(f"Seeding notice: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Supabase database management")
    parser.add_argument("--check", action="store_true", help="Check database connectivity")
    parser.add_argument("--sql", action="store_true", help="Output SQL migration schema")
    parser.add_argument("--migrate", action="store_true", help="Apply SQL migration (requires DB password)")
    parser.add_argument("--seed", action="store_true", help="Seed tables from submission outputs")

    args = parser.parse_args(argv)
    if args.sql:
        return print_sql_schema()
    if args.migrate:
        return run_migration()
    if args.seed:
        return seed_data()
    # Default to status check
    return check_status()


if __name__ == "__main__":
    sys.exit(main())

