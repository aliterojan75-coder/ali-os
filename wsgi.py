"""WSGI entry point for gunicorn: gunicorn wsgi:app"""
from app.webhook import app  # noqa: F401

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
