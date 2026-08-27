"""Turso / libSQL HTTP connection — a drop-in for the small slice of the
sqlite3 API that Ali OS uses.

Why this exists:
    On free PaaS (Koyeb, Render, etc.) the container filesystem is ephemeral,
    so a local SQLite file is wiped on every redeploy/restart. Turso gives us a
    free, persistent, libSQL-compatible database reachable over HTTPS.

The adapter only implements execute/executescript/fetchone/fetchall/lastrowid/
rowcount plus PRAGMA no-ops, which is everything this codebase touches. When
TURSO_DATABASE_URL is not set, the normal local sqlite3 backend in db.py is
used instead.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

import requests


def _is_turso_enabled() -> bool:
    return bool(os.environ.get("TURSO_DATABASE_URL"))


def _strip_sql_comments(sql: str) -> str:
    """Remove single-line (--) and multi-line (/* */) SQL comments while
    preserving quotes/strings/identifiers."""
    out = []
    i = 0
    n = len(sql)
    in_single_quote = False
    in_double_quote = False

    while i < n:
        c = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_single_quote:
            out.append(c)
            if c == "'":
                if nxt == "'":
                    out.append(nxt)
                    i += 2
                    continue
                else:
                    in_single_quote = False
            i += 1
            continue

        if in_double_quote:
            out.append(c)
            if c == '"':
                if nxt == '"':
                    out.append(nxt)
                    i += 2
                    continue
                else:
                    in_double_quote = False
            i += 1
            continue

        if c == "'":
            in_single_quote = True
            out.append(c)
            i += 1
            continue

        if c == '"':
            in_double_quote = True
            out.append(c)
            i += 1
            continue

        # Single-line comment: -- ...
        if c == "-" and nxt == "-":
            i += 2
            while i < n and sql[i] != "\n":
                i += 1
            if i < n and sql[i] == "\n":
                out.append("\n")
                i += 1
            continue

        # Multi-line comment: /* ... */
        if c == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2  # skip */
            out.append(" ")
            continue

        out.append(c)
        i += 1

    return "".join(out)


def _split_statements(script: str) -> list[str]:
    """Split a SQL script into individual statements by semicolon ';',
    respecting single/double quotes so semicolons inside string literals
    or identifiers are preserved."""
    cleaned = _strip_sql_comments(script)

    statements = []
    current = []
    in_single_quote = False
    in_double_quote = False
    i = 0
    n = len(cleaned)

    while i < n:
        c = cleaned[i]
        nxt = cleaned[i + 1] if i + 1 < n else ""

        if in_single_quote:
            current.append(c)
            if c == "'":
                if nxt == "'":
                    current.append(nxt)
                    i += 2
                    continue
                else:
                    in_single_quote = False
            i += 1
            continue

        if in_double_quote:
            current.append(c)
            if c == '"':
                if nxt == '"':
                    current.append(nxt)
                    i += 2
                    continue
                else:
                    in_double_quote = False
            i += 1
            continue

        if c == "'":
            in_single_quote = True
            current.append(c)
            i += 1
            continue

        if c == '"':
            in_double_quote = True
            current.append(c)
            i += 1
            continue

        if c == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(c)
        i += 1

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)

    return statements


class _Row(dict):
    """A row that supports both r['col'] and r['col'] (sqlite3.Row style)."""
    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class TursoCursor:
    def __init__(self, conn: "TursoConnection") -> None:
        self.conn = conn
        self._rows: list[list] = []
        self._cols: list[str] = []
        self.lastrowid: int | None = None
        self.rowcount: int = -1

    def execute(self, sql: str, params: tuple | list = ()) -> "TursoCursor":
        # Normalise libsql-incompatible bits
        stripped = _strip_sql_comments(sql).strip()
        if not stripped:
            return self
        if stripped.lower().startswith("pragma "):
            return self  # no-op over HTTP
        # INSERT … RETURNING id lets us recover last insert id without
        # relying on last_insert_rowid() (which libSQL http supports, but
        # being explicit is portable).
        wants_id = (
            stripped.lower().startswith("insert")
            and " returning " not in stripped.lower()
        )
        if wants_id:
            sql_exec = stripped.rstrip().rstrip(";") + " RETURNING id"
        else:
            sql_exec = stripped

        result = self.conn._pipeline(sql_exec, list(params))
        if not result.get("results"):
            return self
        res = result["results"][0]
        if res.get("type") == "error":
            raise Exception(f"libSQL error: {res.get('error')}")
        resp = res.get("response", {}) or {}
        # The pipeline returns either a bare execute result ({cols, rows,...})
        # or one wrapped under {"result": {...}} depending on server version.
        payload = resp.get("result", resp) if "result" in resp else resp
        self._cols = [c["name"] for c in payload.get("cols", [])]
        self._rows = payload.get("rows", [])
        self.rowcount = int(payload.get("affected_row_count", 0))
        if wants_id and self._rows:
            first = [self._cell(c) for c in self._rows[0]]
            rowdict = dict(zip(self._cols, first))
            self.lastrowid = rowdict.get("id")
        return self

    def executescript(self, script: str) -> None:
        # Split into individual statements and run them in one pipeline batch.
        # PRAGMAs are not supported over the HTTP API and are skipped.
        stmts: list[tuple[str, list]] = []
        for s in _split_statements(script):
            if not s:
                continue
            if s.lower().startswith("pragma "):
                continue
            stmts.append((s, []))
        if not stmts:
            return
        self.conn._pipeline_many(stmts)

    @staticmethod
    def _cell(cell: Any) -> Any:
        # Cells come back as {"type": "...", "value": "..."}; unwrap to native.
        if isinstance(cell, dict) and "type" in cell:
            v = cell.get("value")
            if cell.get("type") == "null" or v is None:
                return None
            if cell.get("type") == "integer":
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return v
            if cell.get("type") == "float":
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return v
            return v
        return cell

    def fetchone(self) -> _Row | None:
        if not self._rows:
            return None
        raw = self._rows.pop(0)
        return _Row(zip(self._cols, [self._cell(c) for c in raw]))

    def fetchall(self) -> list[_Row]:
        rows = [
            _Row(zip(self._cols, [self._cell(c) for c in r]))
            for r in self._rows
        ]
        self._rows = []
        return rows

    # context manager no-op (transactions are per-statement over HTTP)
    def __enter__(self) -> "TursoCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class TursoConnection:
    def __init__(self, database_url: str, auth_token: str) -> None:
        if database_url.startswith("libsql://"):
            database_url = "https://" + database_url[len("libsql://"):]
        self.url = database_url.rstrip("/")
        self.auth_token = auth_token
        self._lock = threading.Lock()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
        }

    def _pipeline(self, sql: str, params: list) -> dict:
        return self._pipeline_many([(sql, params)])

    def _pipeline_many(self, statements: list) -> dict:
        requests_list = []
        for item in statements:
            if isinstance(item, tuple):
                sql, params = item
            elif isinstance(item, list):
                sql, params = item[0], (item[1] if len(item) > 1 else [])
            else:
                sql, params = item, []
            requests_list.append({
                "type": "execute",
                "stmt": {"sql": sql, "args": self._convert_params(params)},
            })
        requests_list.append({"type": "close"})
        body = {"requests": requests_list}
        with self._lock:
            resp = requests.post(
                f"{self.url}/v2/pipeline",
                headers=self._headers(),
                data=json.dumps(body),
                timeout=60,
            )
        if resp.status_code >= 400:
            raise Exception(f"libSQL HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        # Surface the first per-statement error, if any.
        for r in data.get("results", []):
            if r.get("type") == "error":
                raise Exception(f"libSQL error: {r.get('error')}")
        return data

    @staticmethod
    def _convert_params(params: list | tuple) -> list[dict]:
        out = []
        for p in params:
            if p is None:
                out.append({"type": "null"})
            elif isinstance(p, bool):
                out.append({"type": "integer", "value": str(int(p))})
            elif isinstance(p, int):
                out.append({"type": "integer", "value": str(p)})
            elif isinstance(p, float):
                out.append({"type": "float", "value": p})
            else:
                out.append({"type": "text", "value": str(p)})
        return out

    def execute(self, sql: str, params: tuple | list = ()) -> TursoCursor:
        cur = TursoCursor(self)
        return cur.execute(sql, params)

    def executescript(self, script: str) -> None:
        TursoCursor(self).executescript(script)

    def commit(self) -> None:  # no-op, each statement auto-commits
        return None

    def rollback(self) -> None:
        return None

    def cursor(self) -> TursoCursor:
        return TursoCursor(self)


def maybe_connect() -> TursoConnection | None:
    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")
    if not url or not token:
        return None
    return TursoConnection(url, token)
