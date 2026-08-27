"""Specialist agents. Importing a module registers its approval executors."""
from app.agents import wordpress  # noqa: F401

__all__ = ["wordpress"]
