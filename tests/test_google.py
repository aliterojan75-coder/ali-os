"""Tests for Google integrations (GSC + GA4) — mocked, no network."""

import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)

import pytest

from app import db
from app.integrations.google import (
    get_access_token,
    gsc_query,
    gsc_list_sites,
    ga4_run_report,
    get_project_google_data,
    GoogleAuthError,
    GoogleAPIError,
)


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), f"t_{uuid.uuid4().hex}.db")
    from app.config import config
    monkeypatch.setattr(config, "DATABASE_PATH", Path(path))
    db._LOCAL.conn = None
    db.init_db()
    yield
    db._LOCAL.conn = None


def test_get_access_token_success():
    creds = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh"}

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"access_token": "ya29.test-token", "expires_in": 3600}

    with patch("app.integrations.google.requests.post", return_value=mock_resp) as mock_post:
        token = get_access_token(creds)
        assert token == "ya29.test-token"
        mock_post.assert_called_once()


def test_get_access_token_missing_creds():
    creds = {"client_id": "", "client_secret": "", "refresh_token": ""}
    with pytest.raises(GoogleAuthError):
        get_access_token(creds)


def test_get_access_token_failure():
    creds = {"client_id": "id", "client_secret": "secret", "refresh_token": "bad"}

    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.json.return_value = {"error": "invalid_grant", "error_description": "Bad refresh token"}
    mock_resp.status_code = 400
    mock_resp.text = "invalid_grant"

    with patch("app.integrations.google.requests.post", return_value=mock_resp):
        with pytest.raises(GoogleAuthError) as exc:
            get_access_token(creds)
        assert "Bad refresh token" in str(exc.value) or "invalid_grant" in str(exc.value)


def test_gsc_query_success():
    creds = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh", "property_url": "https://example.com/"}

    # Mock get_access_token
    with patch("app.integrations.google.get_access_token", return_value="test-access"):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "rows": [
                {"keys": ["test query"], "clicks": 100, "impressions": 1000, "ctr": 0.1, "position": 5.2}
            ]
        }

        with patch("app.integrations.google.requests.post", return_value=mock_resp):
            data = gsc_query(creds, "https://example.com/", dimensions=["query"], row_limit=10)
            assert "rows" in data
            assert data["rows"][0]["clicks"] == 100


def test_gsc_list_sites():
    creds = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh"}

    with patch("app.integrations.google.get_access_token", return_value="test-access"):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "siteEntry": [
                {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"},
                {"siteUrl": "https://other.com/", "permissionLevel": "siteOwner"},
            ]
        }

        with patch("app.integrations.google.requests.get", return_value=mock_resp):
            sites = gsc_list_sites(creds)
            assert len(sites) == 2
            assert sites[0]["siteUrl"] == "https://example.com/"


def test_ga4_run_report_success():
    creds = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh", "property_id": "123456789"}

    with patch("app.integrations.google.get_access_token", return_value="test-access"):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "rows": [{"dimensionValues": [{"value": "Organic Search"}], "metricValues": [{"value": "100"}]}],
            "totals": [{"metricValues": [{"value": "500"}, {"value": "400"}]}],
        }

        with patch("app.integrations.google.requests.post", return_value=mock_resp):
            data = ga4_run_report(creds, "123456789", metrics=["sessions"], dimensions=["sessionDefaultChannelGroup"])
            assert "rows" in data


def test_get_project_google_data_combined():
    gsc_creds = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh", "property_url": "https://example.com/"}
    ga4_creds = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh", "property_id": "123"}

    mock_gsc_response = {
        "rows": [{"clicks": 100, "impressions": 1000, "ctr": 0.1, "position": 5.0}]
    }
    mock_gsc_top = {
        "rows": [
            {"keys": ["query1"], "clicks": 50, "impressions": 500, "ctr": 0.1, "position": 3.0},
            {"keys": ["query2"], "clicks": 30, "impressions": 300, "ctr": 0.1, "position": 5.0},
        ]
    }
    mock_ga4_response = {
        "rows": [],
        "totals": [{"metricValues": [{"value": "1000"}, {"value": "800"}, {"value": "2000"}, {"value": "50"}, {"value": "0.4"}]}],
    }

    def mock_post_gsc(url, headers=None, json=None, timeout=None):
        mock_resp = MagicMock()
        mock_resp.ok = True
        if "searchAnalytics" in url:
            # Distinguish between overall (dimensions=[]) and top queries/pages
            dims = json.get("dimensions", []) if json else []
            if not dims:
                mock_resp.json.return_value = mock_gsc_response
            else:
                mock_resp.json.return_value = mock_gsc_top
        elif "analyticsdata" in url:
            mock_resp.json.return_value = mock_ga4_response
        else:
            mock_resp.json.return_value = {}
        return mock_resp

    with patch("app.integrations.google.get_access_token", return_value="test-access"):
        with patch("app.integrations.google.requests.post", side_effect=mock_post_gsc):
            data = get_project_google_data(
                gsc_creds=gsc_creds,
                gsc_property="https://example.com/",
                ga4_creds=ga4_creds,
                ga4_property="123",
            )
            assert data["gsc"] is not None
            assert data["gsc"]["totals"]["clicks"] == 100
            assert len(data["gsc"]["top_queries"]) == 2
            assert data["ga4"] is not None
            assert data["errors"] == []
