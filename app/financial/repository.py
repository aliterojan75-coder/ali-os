"""Financial repository — monthly income tracking (redefined §15).

Each project has a monthly contract; track paid/unpaid per Jalali month.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app import db
from app.utils.jalali import today_jalali, gregorian_to_jalali, fa_num
from datetime import datetime

# ── Helpers ──────────────────────────────────────────────────────────────────

def _current_jalali_month() -> str:
    jy, jm, _ = today_jalali()
    return f"{jy:04d}-{jm:02d}"


def _jalali_month_to_gregorian(jalali_month: str) -> str:
    """Convert '1404-06' to Gregorian 'YYYY-MM' for reference."""
    try:
        parts = jalali_month.split("-")
        jy = int(parts[0])
        jm = int(parts[1])
        # First day of Jalali month -> Gregorian
        from app.utils.jalali import jalali_to_gregorian
        gy, gm, _ = jalali_to_gregorian(jy, jm, 1)
        return f"{gy:04d}-{gm:02d}"
    except Exception:
        return ""


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_income(
    *,
    project_id: int,
    amount: float,
    month_jalali: str | None = None,
    currency: str = "IRT",
    due_at: float | None = None,
    status: str = "pending",
    payment_method: str | None = None,
    notes: str | None = None,
    created_by: int | None = None,
) -> sqlite3.Row:
    """Create monthly income record. month_jalali defaults to current Jalali month."""
    if not month_jalali:
        month_jalali = _current_jalali_month()

    # Validate month format
    if len(month_jalali) != 7 or month_jalali[4] != "-":
        raise ValueError("month_jalali باید به صورت YYYY-MM باشد، مثلاً 1404-06")

    month_greg = _jalali_month_to_gregorian(month_jalali)
    t = db.now()
    uid = db.new_uid("inc")

    # Due at defaults to 5th of next Gregorian month? Or end of Jalali month?
    # For simplicity, due at = now + 5 days if not provided, or 1st of next Jalali month
    if due_at is None:
        # Due at end of Jalali month
        try:
            jy, jm = map(int, month_jalali.split("-"))
            from app.utils.jalali import jalali_month_length, jalali_to_gregorian
            last_day = jalali_month_length(jy, jm)
            gy, gm, gd = jalali_to_gregorian(jy, jm, last_day)
            due_dt = datetime(gy, gm, gd, 23, 59, 59)
            due_at = due_dt.timestamp()
        except Exception:
            due_at = t + 5 * 86400

    status = status if status in ("pending", "paid", "overdue", "cancelled", "partial") else "pending"

    cur = db.execute(
        """INSERT INTO project_incomes
           (income_uid, project_id, amount, currency, month_jalali, month_gregorian,
            due_at, status, payment_method, notes, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (uid, project_id, amount, currency, month_jalali, month_greg, due_at, status, payment_method, notes, created_by, t, t),
    )
    return db.query_one("SELECT * FROM project_incomes WHERE id=?", (cur.lastrowid,))


def get_income(income_uid: str) -> sqlite3.Row | None:
    return db.query_one("SELECT * FROM project_incomes WHERE income_uid=?", (income_uid,))


def list_incomes(
    *,
    project_id: int | None = None,
    status: str | None = None,
    month_jalali: str | None = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    sql = """SELECT i.*, p.name AS project_name, p.slug AS project_slug
             FROM project_incomes i JOIN projects p ON p.id=i.project_id WHERE 1=1"""
    params: list[Any] = []
    if project_id is not None:
        sql += " AND i.project_id=?"
        params.append(project_id)
    if status:
        sql += " AND i.status=?"
        params.append(status)
    if month_jalali:
        sql += " AND i.month_jalali=?"
        params.append(month_jalali)
    sql += " ORDER BY i.month_jalali DESC, i.due_at DESC LIMIT ?"
    params.append(limit)
    return db.query_all(sql, tuple(params))


def mark_paid(
    income_uid: str,
    *,
    paid_at: float | None = None,
    payment_method: str | None = None,
    transaction_ref: str | None = None,
) -> sqlite3.Row | None:
    t = paid_at or db.now()
    sets = ["status='paid'", "paid_at=?", "updated_at=?"]
    params: list[Any] = [t, db.now()]

    if payment_method:
        sets.append("payment_method=?")
        params.append(payment_method)
    if transaction_ref:
        sets.append("transaction_ref=?")
        params.append(transaction_ref)

    params.append(income_uid)
    db.execute(f"UPDATE project_incomes SET {', '.join(sets)} WHERE income_uid=?", tuple(params))
    return get_income(income_uid)


def mark_overdue_if_needed() -> int:
    """Mark pending incomes past due date as overdue. Returns count."""
    now = db.now()
    rows = db.query_all(
        "SELECT income_uid FROM project_incomes WHERE status='pending' AND due_at IS NOT NULL AND due_at < ?",
        (now,),
    )
    for r in rows:
        db.execute(
            "UPDATE project_incomes SET status='overdue', updated_at=? WHERE income_uid=?",
            (now, r["income_uid"]),
        )
    return len(rows)


def update_income(income_uid: str, **fields: Any) -> sqlite3.Row | None:
    allowed = {"amount", "currency", "month_jalali", "due_at", "paid_at", "status", "payment_method", "transaction_ref", "notes", "project_id"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "status" and v not in ("pending", "paid", "overdue", "cancelled", "partial"):
            continue
        sets.append(f"{k}=?")
        params.append(v)
    if not sets:
        return get_income(income_uid)
    sets.append("updated_at=?")
    params.extend([db.now(), income_uid])
    db.execute(f"UPDATE project_incomes SET {', '.join(sets)} WHERE income_uid=?", tuple(params))
    return get_income(income_uid)


def delete_income(income_uid: str) -> bool:
    cur = db.execute("DELETE FROM project_incomes WHERE income_uid=?", (income_uid,))
    return getattr(cur, "rowcount", 1) > 0


def monthly_summary(*, project_id: int | None = None) -> dict:
    """Summary per Jalali month."""
    mark_overdue_if_needed()

    # Total per month
    sql = "SELECT month_jalali, SUM(CASE WHEN status='paid' THEN amount ELSE 0 END) AS paid, SUM(amount) AS total, COUNT(*) AS cnt FROM project_incomes"
    params: list[Any] = []
    if project_id is not None:
        sql += " WHERE project_id=?"
        params.append(project_id)
    sql += " GROUP BY month_jalali ORDER BY month_jalali DESC LIMIT 12"

    rows = db.query_all(sql, tuple(params))
    months = []
    for r in rows:
        months.append({
            "month_jalali": r["month_jalali"],
            "paid": float(r["paid"] or 0),
            "total": float(r["total"] or 0),
            "count": r["cnt"],
            "paid_percent": round(float(r["paid"] or 0) / float(r["total"] or 1) * 100) if r["total"] else 0,
        })

    # Overall
    sql2 = "SELECT SUM(CASE WHEN status='paid' THEN amount ELSE 0 END) AS paid, SUM(amount) AS total, COUNT(*) AS cnt FROM project_incomes"
    if project_id is not None:
        sql2 += " WHERE project_id=?"
        row = db.query_one(sql2, (project_id,))
    else:
        row = db.query_one(sql2)

    total_paid = float(row["paid"] or 0) if row else 0
    total_expected = float(row["total"] or 0) if row else 0

    # Overdue list
    overdue = list_incomes(status="overdue", project_id=project_id, limit=20)
    pending = list_incomes(status="pending", project_id=project_id, limit=20)

    # Current month
    current_month = _current_jalali_month()
    current_incomes = list_incomes(month_jalali=current_month, project_id=project_id, limit=50)

    return {
        "current_month": current_month,
        "months": months,
        "total_paid": total_paid,
        "total_expected": total_expected,
        "collection_rate": round(total_paid / total_expected * 100) if total_expected else 0,
        "overdue": [dict(r) for r in overdue],
        "pending": [dict(r) for r in pending],
        "current_month_incomes": [dict(r) for r in current_incomes],
    }


def project_contracts_summary() -> list[dict]:
    """List projects with their monthly contract amount (average of last 3 paid)."""
    projects = db.query_all("SELECT * FROM projects WHERE status='active' ORDER BY name")
    result = []
    for p in projects:
        # Average of last 3 paid incomes as contract amount estimate
        rows = db.query_all(
            "SELECT amount FROM project_incomes WHERE project_id=? AND status='paid' ORDER BY month_jalali DESC LIMIT 3",
            (p["id"],),
        )
        avg = sum(float(r["amount"] or 0) for r in rows) / len(rows) if rows else 0

        # Current month status
        current_month = _current_jalali_month()
        cur = db.query_one(
            "SELECT status, amount FROM project_incomes WHERE project_id=? AND month_jalali=?",
            (p["id"], current_month),
        )
        cur_status = cur["status"] if cur else "not_created"
        cur_amount = float(cur["amount"] or 0) if cur else 0

        # Overdue count
        overdue_cnt = db.query_one(
            "SELECT COUNT(*) AS c FROM project_incomes WHERE project_id=? AND status='overdue'",
            (p["id"],),
        )["c"]

        result.append({
            "id": p["id"],
            "slug": p["slug"],
            "name": p["name"],
            "avg_contract": avg,
            "current_month_status": cur_status,
            "current_month_amount": cur_amount,
            "overdue_count": overdue_cnt,
        })
    return result
