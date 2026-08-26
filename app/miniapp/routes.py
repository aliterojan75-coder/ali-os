"""Routes that serve the Mini App dashboard (static SPA)."""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, send_from_directory

STATIC_DIR = Path(__file__).resolve().parent / "static"

spa = Blueprint("spa", __name__)


@spa.get("/")
def root():
    return send_from_directory(STATIC_DIR, "index.html")


@spa.get("/app")
def app_page():
    return send_from_directory(STATIC_DIR, "index.html")
