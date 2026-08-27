"""Three-level risk model for the Approval System (§19).

🟢 green  — reversible, no cost, no external side effect → auto-executed,
            still logged in pending_actions for the audit trail.
🟡 yellow — external side effect or meaningful change → ONE approval by Ali.
🔴 red    — irreversible, costly, public or customer-facing → TWO-step
            approval (confirm, then final confirm) with a short TTL.

Agents never pick a risk level ad hoc: they declare an action_type and this
module resolves the level, so policy stays in one place.
"""
from __future__ import annotations

GREEN, YELLOW, RED = "green", "yellow", "red"

EMOJI = {GREEN: "🟢", YELLOW: "🟡", RED: "🔴"}
LABEL_FA = {
    GREEN: "کم‌خطر (اجرای مستقیم)",
    YELLOW: "نیازمند تأیید",
    RED: "پرخطر (تأیید دو مرحله‌ای)",
}

# Approvals required per level.
APPROVALS_REQUIRED = {GREEN: 0, YELLOW: 1, RED: 2}

# How long an approval card stays actionable, per level (seconds).
TTL_SECONDS = {
    GREEN: 15 * 60,
    YELLOW: 24 * 60 * 60,
    RED: 2 * 60 * 60,
}

# Explicit policy table: action_type → risk level.
ACTION_RISK: dict[str, str] = {
    # internal, reversible
    "task.create": GREEN,
    "task.update_status": GREEN,
    "memory.add": GREEN,
    "decision.record": GREEN,
    "project.dossier_read": GREEN,
    "kpi.add": GREEN,
    "person.add": GREEN,
    "crm.create_contact": GREEN,
    "crm.add_interaction": GREEN,
    "crm.create_deal": GREEN,
    "notification.create": GREEN,
    "content.draft_create": GREEN,
    "content.draft_update": GREEN,
    "seo.audit": GREEN,
    "income.create": GREEN,
    "financial.create_income": GREEN,
    "income.update": GREEN,
    "financial.update_income": GREEN,
    "income.mark_paid": GREEN,
    "financial.mark_paid": GREEN,
    # changes with real consequences
    "task.delete": YELLOW,
    "project.update": YELLOW,
    "budget.add_line": YELLOW,
    "wordpress.create_draft": YELLOW,
    "wordpress.update_post": YELLOW,
    "content.generate": YELLOW,
    "content.publish_draft": YELLOW,
    "notification.send": YELLOW,
    "integration.connect": YELLOW,
    "crm.update_contact": YELLOW,
    "crm.update_deal": YELLOW,
    "crm.update_deal_stage": YELLOW,
    "crm.delete_interaction": YELLOW,
    "content.delete_draft": YELLOW,
    "income.delete": YELLOW,
    "financial.delete_income": YELLOW,
    "financial.send_reminder": YELLOW,
    "sales.send_followup": YELLOW,
    "income.send_reminder": YELLOW,
    # irreversible / public / costly
    "wordpress.publish": RED,
    "wordpress.delete_post": RED,
    "project.delete": RED,
    "message.send_to_client": RED,
    "ads.change_budget": RED,
    "payment.execute": RED,
    "integration.revoke": RED,
    "social.publish": RED,
    "crm.delete_contact": RED,
    "crm.delete_deal": RED,
    "content.publish": RED,
}

# Keyword fallback for action types not yet in the table — default to the safe
# side rather than silently treating an unknown action as green.
_RED_HINTS = ("delete", "publish", "payment", "pay", "charge", "revoke", "send_to_client")
_YELLOW_HINTS = ("update", "create", "write", "send", "connect", "generate", "upload")


def classify(action_type: str) -> str:
    """Return the risk level for an action type."""
    key = (action_type or "").strip().lower()
    if key in ACTION_RISK:
        return ACTION_RISK[key]
    for hint in _RED_HINTS:
        if hint in key:
            return RED
    for hint in _YELLOW_HINTS:
        if hint in key:
            return YELLOW
    return YELLOW  # unknown → never auto-execute


def approvals_required(risk: str) -> int:
    return APPROVALS_REQUIRED.get(risk, 1)


def ttl_for(risk: str) -> int:
    return TTL_SECONDS.get(risk, 24 * 60 * 60)


def is_auto(risk: str) -> bool:
    return risk == GREEN
