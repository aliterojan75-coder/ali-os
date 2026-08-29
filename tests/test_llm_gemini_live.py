"""Optional live Gemini compatibility smoke tests.

Run only when a real Gemini key is present:

    RUN_LIVE_LLM=1 LLM_API_KEY=... \
      LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai \
      LLM_MODEL=gemini-3.7-flash \
      python -m pytest tests/test_llm_gemini_live.py -q

These tests are intentionally skipped in CI/default local runs because the repo
must never contain or require a committed API key.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")

import pytest

from app.llm import LLMMessage
from app.llm.openai_compatible import OpenAICompatibleProvider


def _has_live_key() -> bool:
    key = os.environ.get("LLM_API_KEY", "")
    return os.environ.get("RUN_LIVE_LLM") == "1" and key and key != "test-key"


@pytest.mark.skipif(not _has_live_key(), reason="needs RUN_LIVE_LLM=1 and real LLM_API_KEY")
def test_gemini_openai_structured_output_live(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "LLM_BASE_URL", os.environ.get("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"))
    monkeypatch.setattr(config, "LLM_MODEL", os.environ.get("LLM_MODEL", "gemini-3.7-flash"))
    monkeypatch.setattr(config, "LLM_API_KEY", os.environ["LLM_API_KEY"])

    provider = OpenAICompatibleProvider()
    data = provider.structured_output([
        LLMMessage(role="system", content="You return only valid JSON."),
        LLMMessage(role="user", content='Return exactly this object in Persian values: {"ok": true, "answer": "سلام"}'),
    ], temperature=0.0, max_tokens=80)

    assert data.get("ok") is True
    assert "answer" in data
