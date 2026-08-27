"""Persistence for integration credentials (§20).

Secrets are encrypted with Fernet before they are written and are NEVER
returned to any client — the API only ever sees masked values via
`public_view()`. Agents that genuinely need a secret call `credentials()`.

Note on uniqueness: SQLite treats NULLs as distinct in UNIQUE constraints, so
a global (project-less) integration would not be de-duplicated by the schema.
`upsert()` therefore looks the row up explicitly before inserting.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app import db
from app.integrations import catalog
from app.integrations.crypto import CryptoError, decrypt, encrypt, mask
from app.logging_config import get_logger

log = get_logger("integrations.store")

STATUS_PENDING = "pending"
STATUS_CONNECTED = "connected"
STATUS_ERROR = "error"
STATUS_DISABLED = "disabled"


def find(service: str, project_id: int | None) -> sqlite3.Row | None:
    if project_id is None:
        return db.query_one(
            "SELECT * FROM integrations WHERE service=? AND project_id IS NULL",
            (service,),
        )
    return db.query_one(
        "SELECT * FROM integrations WHERE service=? AND project_id=?",
        (service, project_id),
    )


def get_by_id(integration_id: int) -> sqlite3.Row | None:
    # Join the project so public_view() can label the connection.
    return db.query_one(
        "SELECT i.*, p.name AS project_name, p.slug AS project_slug "
        "FROM integrations i LEFT JOIN projects p ON p.id=i.project_id "
        "WHERE i.id=?",
        (integration_id,),
    )


def list_all(project_id: int | None = None,
             include_global: bool = True) -> list[sqlite3.Row]:
    sql = ("SELECT i.*, p.name AS project_name, p.slug AS project_slug "
           "FROM integrations i LEFT JOIN projects p ON p.id=i.project_id")
    params: list[Any] = []
    if project_id is not None:
        sql += " WHERE (i.project_id=?" + (" OR i.project_id IS NULL)" if include_global else ")")
        params.append(project_id)
    sql += " ORDER BY i.service"
    return db.query_all(sql, tuple(params))


def _load_credentials(row: Any) -> dict:
    blob = row["credentials_enc"] or ""
    if not blob:
        return {}
    try:
        return json.loads(decrypt(blob))
    except CryptoError:
        raise
    except Exception:  # noqa: BLE001 — corrupt blob must not crash callers
        log.warning("integration.bad_blob",
                    extra={"extra_fields": {"service": row["service"]}})
        return {}


def credentials(service: str, project_id: int | None = None) -> dict:
    """Decrypted credentials for an agent. Raises if the key is unavailable."""
    row = find(service, project_id)
    if row is None and project_id is not None:
        row = find(service, None)          # fall back to a global connection
    if row is None:
        return {}
    return _load_credentials(row)


def upsert(
    *,
    service: str,
    values: dict,
    project_id: int | None = None,
    label: str | None = None,
    created_by: int | None = None,
    merge: bool = True,
) -> sqlite3.Row:
    """Create or update an integration, encrypting the secret fields.

    With `merge=True` an empty secret field keeps the previously stored value,
    so Ali can edit a site URL without retyping the application password.
    """
    existing = find(service, project_id)
    previous = _load_credentials(existing) if existing is not None else {}

    merged = dict(previous) if merge else {}
    merged.update(values)

    secrets = catalog.secret_keys(service)
    public = {k: v for k, v in merged.items() if k not in secrets}

    blob = encrypt(json.dumps(merged, ensure_ascii=False)) if merged else ""
    t = db.now()

    if existing is not None:
        db.execute(
            """UPDATE integrations
               SET credentials_enc=?, public_json=?, label=?, status=?,
                   last_error=NULL, updated_at=?
               WHERE id=?""",
            (blob, json.dumps(public, ensure_ascii=False), label,
             STATUS_PENDING, t, existing["id"]),
        )
        return get_by_id(existing["id"])

    cur = db.execute(
        """INSERT INTO integrations
           (project_id, service, label, credentials_enc, public_json, status,
            created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project_id, service, label, blob,
         json.dumps(public, ensure_ascii=False), STATUS_PENDING,
         created_by, t, t),
    )
    return get_by_id(cur.lastrowid)


def set_status(integration_id: int, status: str, error: str | None = None) -> None:
    db.execute(
        "UPDATE integrations SET status=?, last_error=?, last_checked_at=?, updated_at=? WHERE id=?",
        (status, error, db.now(), db.now(), integration_id),
    )


def delete(integration_id: int) -> bool:
    row = get_by_id(integration_id)
    if row is None:
        return False
    db.execute("DELETE FROM integrations WHERE id=?", (integration_id,))
    return True


def public_view(row: Any) -> dict:
    """Safe representation for the Mini App — secrets are masked, never sent."""
    service = catalog.get(row["service"])
    try:
        creds = _load_credentials(row)
        readable = True
    except CryptoError:
        creds, readable = {}, False

    secrets = catalog.secret_keys(row["service"])
    fields: dict[str, Any] = {}
    for key, value in creds.items():
        fields[key] = mask(str(value)) if key in secrets else value

    project_name = None
    try:
        project_name = row["project_name"]
    except Exception:  # noqa: BLE001 — row fetched without the join
        project_name = None

    return {
        "id": row["id"],
        "service": row["service"],
        "service_name": service.name if service else row["service"],
        "icon": service.icon if service else "🔌",
        "project_id": row["project_id"],
        "project_name": project_name,
        "label": row["label"],
        "status": row["status"],
        "last_error": row["last_error"],
        "last_checked_at": row["last_checked_at"],
        "updated_at": row["updated_at"],
        "configured_fields": sorted(fields.keys()),
        "values": fields,
        "readable": readable,
    }
