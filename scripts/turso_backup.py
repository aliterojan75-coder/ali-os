"""Nightly Turso → SQLite snapshot (P1).

Pulls a full consistent replica of the hosted Turso DB into a local file,
verifies integrity, and exits non-zero on any failure so CI reports it loudly.
Run by .github/workflows/nightly-backup.yml; can also be run manually:

    TURSO_DATABASE_URL=... TURSO_AUTH_TOKEN=... python scripts/turso_backup.py

Note: DATABASE_PATH stays supported in config, so a snapshot can simply be
pointed at locally (`DATABASE_PATH=backup/... gunicorn wsgi:app`) for browsing
— that is also the easiest partial-restore path.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("TURSO_DATABASE_URL", ""))
    ap.add_argument("--token", default=os.environ.get("TURSO_AUTH_TOKEN", ""))
    ap.add_argument("--out", default="backup/ali_os_snapshot.sqlite")
    args = ap.parse_args()

    if not args.url:
        print("TURSO_DATABASE_URL is required", file=sys.stderr)
        return 2

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    if os.path.exists(args.out):
        os.remove(args.out)

    from libsql import connect  # provided by the libsql-client package

    conn = connect(f"file:{args.out}", sync_url=args.url, auth_token=args.token or None)
    conn.sync()  # pull the full snapshot into the local file
    conn.close()

    with sqlite3.connect(args.out) as c:
        ok = c.execute("PRAGMA integrity_check").fetchone()[0]
        tables = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    if ok != "ok":
        print(f"integrity_check failed: {ok}", file=sys.stderr)
        return 1

    size = os.path.getsize(args.out)
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    print(f"backup ok @ {stamp}: {args.out} ({size:,} bytes, {tables} tables)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
