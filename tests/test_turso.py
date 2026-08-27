"""Tests for Turso / libSQL HTTP connection adapter, comment stripping,
statement splitting, and execution pipeline."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)

import pytest  # noqa: E402

from app.db import SCHEMA  # noqa: E402
from app.turso import (  # noqa: E402
    TursoConnection,
    TursoCursor,
    _Row,
    _split_statements,
    _strip_sql_comments,
)


def test_strip_sql_comments_single_line():
    sql = "SELECT 1; -- this is a comment\nSELECT 2;"
    stripped = _strip_sql_comments(sql)
    assert "-- this is a comment" not in stripped
    assert "SELECT 1;" in stripped
    assert "SELECT 2;" in stripped


def test_strip_sql_comments_multi_line():
    sql = "SELECT 1; /* multi\nline\ncomment */ SELECT 2;"
    stripped = _strip_sql_comments(sql)
    assert "multi" not in stripped
    assert "SELECT 1;" in stripped
    assert "SELECT 2;" in stripped


def test_strip_sql_comments_preserves_string_literal():
    sql = "SELECT 'hello -- world', '/* not comment */' FROM tbl;"
    stripped = _strip_sql_comments(sql)
    assert "hello -- world" in stripped
    assert "/* not comment */" in stripped


def test_strip_sql_comments_preserves_double_quotes():
    sql = 'SELECT "col--name" FROM "my/*table*/";'
    stripped = _strip_sql_comments(sql)
    assert '"col--name"' in stripped
    assert '"my/*table*/"' in stripped


def test_strip_sql_comments_escaped_quotes():
    sql = "SELECT 'it''s -- safe' AS col; -- end comment"
    stripped = _strip_sql_comments(sql)
    assert "it''s -- safe" in stripped
    assert "end comment" not in stripped


def test_strip_sql_comments_empty_and_whitespace():
    assert _strip_sql_comments("") == ""
    assert _strip_sql_comments("   \n\t  ").strip() == ""
    assert _strip_sql_comments("-- only comment\n").strip() == ""


def test_split_statements_basic():
    script = "CREATE TABLE a (id INT); CREATE TABLE b (id INT);"
    stmts = _split_statements(script)
    assert len(stmts) == 2
    assert stmts[0] == "CREATE TABLE a (id INT)"
    assert stmts[1] == "CREATE TABLE b (id INT)"


def test_split_statements_semicolon_in_string():
    script = "INSERT INTO logs (msg) VALUES ('first; part'); SELECT 1;"
    stmts = _split_statements(script)
    assert len(stmts) == 2
    assert stmts[0] == "INSERT INTO logs (msg) VALUES ('first; part')"
    assert stmts[1] == "SELECT 1"


def test_split_statements_semicolon_in_double_quotes():
    script = 'SELECT "col;name" FROM t; SELECT 2;'
    stmts = _split_statements(script)
    assert len(stmts) == 2
    assert stmts[0] == 'SELECT "col;name" FROM t'
    assert stmts[1] == "SELECT 2"


def test_split_statements_semicolon_in_comment():
    script = """
    -- credentials are encrypted at rest; the key lives only in env.
    CREATE TABLE IF NOT EXISTS integrations (
        id INTEGER PRIMARY KEY
    );
    """
    stmts = _split_statements(script)
    assert len(stmts) == 1
    assert stmts[0].startswith("CREATE TABLE IF NOT EXISTS integrations")
    assert "the key lives only in env" not in stmts[0]


def test_split_statements_multi_line_comment_with_semicolon():
    script = "/* comment with ; inside */ CREATE TABLE test (id INT); /* another; */"
    stmts = _split_statements(script)
    assert len(stmts) == 1
    assert stmts[0] == "CREATE TABLE test (id INT)"


def test_split_statements_trailing_semicolons_and_whitespace():
    script = ";;; \n\n ;  SELECT 1; ;;\n"
    stmts = _split_statements(script)
    assert len(stmts) == 1
    assert stmts[0] == "SELECT 1"


def test_split_statements_no_trailing_semicolon():
    script = "SELECT 1"
    stmts = _split_statements(script)
    assert stmts == ["SELECT 1"]


def test_turso_cursor_executescript_skips_pragmas():
    conn = MagicMock(spec=TursoConnection)
    cur = TursoCursor(conn)
    script = """
    PRAGMA journal_mode=WAL;
    PRAGMA foreign_keys=ON;
    CREATE TABLE test (id INT);
    """
    cur.executescript(script)
    assert conn._pipeline_many.called
    calls = conn._pipeline_many.call_args[0][0]
    assert len(calls) == 1
    assert calls[0][0] == "CREATE TABLE test (id INT)"


def test_turso_cursor_executescript_empty_script_no_request():
    conn = MagicMock(spec=TursoConnection)
    cur = TursoCursor(conn)
    cur.executescript("-- only comment;\n; /* another */")
    assert not conn._pipeline_many.called


def test_turso_convert_params():
    params = [None, True, False, 42, 3.14, "hello"]
    converted = TursoConnection._convert_params(params)
    assert converted == [
        {"type": "null"},
        {"type": "integer", "value": "1"},
        {"type": "integer", "value": "0"},
        {"type": "integer", "value": "42"},
        {"type": "float", "value": 3.14},
        {"type": "text", "value": "hello"},
    ]


def test_row_access_by_name_and_index():
    row = _Row({"id": 10, "name": "Ali", "role": "admin"})
    assert row["id"] == 10
    assert row["name"] == "Ali"
    assert row[0] == 10
    assert row[1] == "Ali"
    assert row[2] == "admin"
    assert len(row) == 3


def test_cell_unwrapping_types():
    assert TursoCursor._cell({"type": "null"}) is None
    assert TursoCursor._cell({"type": "integer", "value": "123"}) == 123
    assert TursoCursor._cell({"type": "float", "value": 45.67}) == 45.67
    assert TursoCursor._cell({"type": "text", "value": "foo"}) == "foo"
    assert TursoCursor._cell("plain") == "plain"


def test_turso_cursor_execute_insert_wants_id():
    conn = MagicMock(spec=TursoConnection)
    conn._pipeline.return_value = {
        "results": [{
            "type": "ok",
            "response": {
                "result": {
                    "cols": [{"name": "id"}],
                    "rows": [[{"type": "integer", "value": "7"}]],
                    "affected_row_count": 1,
                }
            }
        }]
    }
    cur = TursoCursor(conn)
    cur.execute("INSERT INTO users (name) VALUES (?)", ("Ali",))
    assert conn._pipeline.called
    called_sql = conn._pipeline.call_args[0][0]
    assert called_sql.endswith("RETURNING id")
    assert cur.lastrowid == 7
    assert cur.rowcount == 1


def test_turso_cursor_execute_pragma_noop():
    conn = MagicMock(spec=TursoConnection)
    cur = TursoCursor(conn)
    res = cur.execute("PRAGMA foreign_keys=ON;")
    assert res is cur
    assert not conn._pipeline.called


def test_schema_parsing_produces_valid_statements():
    stmts = _split_statements(SCHEMA)
    assert len(stmts) > 0
    for stmt in stmts:
        assert stmt.strip(), "Statement should not be empty"
        # Verify statement does not contain dangling comment text
        assert not stmt.strip().startswith("--"), "Statement should not be a comment"
        assert not stmt.strip().startswith("/*"), "Statement should not be a comment"
        # Verify it starts with a valid SQL keyword
        first_word = stmt.strip().split()[0].upper()
        assert first_word in ("CREATE", "INSERT", "ALTER", "DROP", "SELECT"), f"Unexpected start: {stmt[:30]}"


def test_mock_libsql_server_rejects_empty_statement():
    """Simulates real libSQL behavior where empty or comment-only SQL string
    causes SQL_PARSE_ERROR."""
    def fake_libsql_parser(sql: str):
        # libSQL engine parser error simulation
        stripped = _strip_sql_comments(sql).strip()
        if not stripped:
            return {
                "type": "error",
                "error": {
                    "message": "SQL string does not contain any statement",
                    "code": "SQL_PARSE_ERROR",
                },
            }
        return {"type": "ok", "response": {"result": {"cols": [], "rows": [], "affected_row_count": 0}}}

    # A comment-only statement causes error in libSQL
    err_res = fake_libsql_parser("-- credentials are encrypted at rest")
    assert err_res["type"] == "error"
    assert err_res["error"]["code"] == "SQL_PARSE_ERROR"

    # With proper splitting, no empty statements are produced
    valid_res = fake_libsql_parser("CREATE TABLE foo (id INT)")
    assert valid_res["type"] == "ok"


def test_mock_libsql_server_full_schema_executescript():
    """Runs full Ali OS SCHEMA through executescript with a mock libSQL HTTP
    pipeline that parses and validates each statement like real libSQL."""
    # Local SQLite backing the mock libSQL server to verify syntax validity
    temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_db.close()
    mem_conn = sqlite3.connect(temp_db.name)

    def mock_post(url, headers=None, data=None, timeout=60):
        body = json.loads(data)
        results = []
        for req in body.get("requests", []):
            if req.get("type") == "close":
                continue
            if req.get("type") == "execute":
                stmt = req.get("stmt", {})
                sql = stmt.get("sql", "")
                stripped = sql.strip()
                if not stripped:
                    results.append({
                        "type": "error",
                        "error": {
                            "message": "SQL string does not contain any statement",
                            "code": "SQL_PARSE_ERROR",
                        },
                    })
                    continue
                try:
                    mem_conn.execute(sql)
                    results.append({
                        "type": "ok",
                        "response": {
                            "result": {
                                "cols": [],
                                "rows": [],
                                "affected_row_count": 0,
                            }
                        },
                    })
                except Exception as e:
                    results.append({
                        "type": "error",
                        "error": {"message": str(e), "code": "SQL_ERROR"},
                    })

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": results}
        return mock_resp

    with patch("requests.post", side_effect=mock_post):
        conn = TursoConnection("libsql://mock-db.turso.io", "mock-token")
        cur = conn.cursor()
        # Execute the full Ali OS SCHEMA
        cur.executescript(SCHEMA)

    # Verify all 14 tables were created in the SQLite database
    tables = [
        row[0]
        for row in mem_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    expected_tables = {
        "users",
        "projects",
        "tasks",
        "memories",
        "decisions",
        "conversations",
        "messages",
        "events",
        "tool_calls",
        "pending_actions",
        "project_kpis",
        "project_budget",
        "project_people",
        "integrations",
    }
    assert expected_tables.issubset(set(tables)), f"Missing tables: {expected_tables - set(tables)}"
    mem_conn.close()
    os.unlink(temp_db.name)
