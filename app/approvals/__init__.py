"""Approval System (§19) — three risk levels, Telegram inline approval.

Importing this package registers the built-in executors, so any module that
does `from app.approvals import request_action` gets a fully wired gateway.
"""
from app.approvals import actions  # noqa: F401  (side effect: registers executors)
from app import agents  # noqa: F401  (side effect: registers agent executors)
from app.approvals.gateway import (  # noqa: F401
    ActionResult,
    DecisionError,
    approve,
    build_keyboard,
    final_text,
    handle_callback,
    is_approval_callback,
    make_callback,
    parse_callback,
    reject,
    render_card,
    request_action,
)
from app.approvals.registry import executor, known_actions, run  # noqa: F401
from app.approvals.risk import EMOJI, LABEL_FA, classify  # noqa: F401

__all__ = [
    "request_action", "handle_callback", "approve", "reject", "classify",
    "render_card", "build_keyboard", "final_text", "executor", "known_actions",
    "run", "ActionResult", "DecisionError", "is_approval_callback",
    "make_callback", "parse_callback", "EMOJI", "LABEL_FA",
]
