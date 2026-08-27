"""Routes that serve the Mini App dashboard (static SPA)."""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, send_from_directory

STATIC_DIR = Path(__file__).resolve().parent / "static"

spa = Blueprint("spa", __name__)


def _no_store(resp):
    """The dashboard is a single deployed file; never let a stale copy stick.

    Telegram's in-app webview caches aggressively, which previously meant a
    deploy could leave Ali staring at an old UI until he cleared the cache.
    """
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@spa.get("/")
def root():
    return _no_store(send_from_directory(STATIC_DIR, "index.html"))


@spa.get("/app")
def app_page():
    return _no_store(send_from_directory(STATIC_DIR, "index.html"))


@spa.get("/static/<path:filename>")
def static_files(filename: str):
    """Serve the dashboard's own assets (charts.js).

    Flask's built-in /static is bound to the app root, not this blueprint's
    directory, so the Mini App's assets need their own explicit route.
    """
    return _no_store(send_from_directory(STATIC_DIR, filename))
