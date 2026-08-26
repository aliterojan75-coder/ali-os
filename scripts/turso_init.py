"""Initialise the schema on a remote Turso/libSQL database.

Reads TURSO_DATABASE_URL and TURSO_AUTH_TOKEN from the environment. Run once
after creating the database from the Turso dashboard/CLI:

    python -m scripts.turso_init

It is idempotent (CREATE TABLE IF NOT EXISTS) and safe to re-run.
"""
from __future__ import annotations

import os
import sys

# Allow running as `python scripts/turso_init.py` from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, seed  # noqa: E402
from app.config import config  # noqa: E402


def main() -> None:
    if not os.environ.get("TURSO_DATABASE_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
        print("Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN first.")
        sys.exit(1)
    print(f"Initialising schema on: {config.TURSO_DATABASE_URL_DISPLAY if hasattr(config,'TURSO_DATABASE_URL_DISPLAY') else os.environ.get('TURSO_DATABASE_URL')}")
    db.init_db()
    seed.seed_all()
    print("✅ Schema + seed applied.")


if __name__ == "__main__":
    main()
