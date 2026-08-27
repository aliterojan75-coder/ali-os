"""Executor registry for approved actions.

An action type is only executable if some module registered a handler for it:

    @executor("task.create")
    def _create_task(payload: dict, ctx: dict) -> dict:
        ...

The gateway calls `run(action_type, payload, ctx)` ONLY after the approval
rules in `app.approvals.gateway` are satisfied — no agent may reach an
executor directly, which is what enforces §19 ("no 🟡/🔴 action without an
approved pending record").
"""
from __future__ import annotations

from typing import Any, Callable

Executor = Callable[[dict, dict], Any]

_REGISTRY: dict[str, Executor] = {}


class UnknownAction(KeyError):
    pass


def executor(action_type: str) -> Callable[[Executor], Executor]:
    def decorator(fn: Executor) -> Executor:
        _REGISTRY[action_type] = fn
        return fn
    return decorator


def register(action_type: str, fn: Executor) -> None:
    _REGISTRY[action_type] = fn


def has(action_type: str) -> bool:
    return action_type in _REGISTRY


def known_actions() -> list[str]:
    return sorted(_REGISTRY)


def run(action_type: str, payload: dict, ctx: dict | None = None) -> Any:
    fn = _REGISTRY.get(action_type)
    if fn is None:
        raise UnknownAction(f"No executor registered for action '{action_type}'")
    return fn(payload or {}, ctx or {})
