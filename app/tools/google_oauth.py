"""One-time helper to get a Google OAuth refresh token (§4, §5).

Usage:
  1. Create a Google Cloud Project, enable Search Console API and Analytics Data API
  2. Create OAuth Client ID (Desktop app) — get client_id and client_secret
  3. Run:
     python -m app.tools.google_oauth --client-id YOUR_ID --client-secret YOUR_SECRET --port 8080

It will open a browser for you to authorize, then print the refresh token.

For headless servers, use --no-browser and paste the URL manually.

The refresh token is long-lived and should be stored in the integrations panel.
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
import threading
import time
import urllib.parse
import webbrowser
from typing import Any

import requests


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Request both Search Console and GA4 scopes at once — one refresh token covers both
SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]


def build_auth_url(client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",  # force refresh_token
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            CallbackHandler.code = qs["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
                b"<h2>Authorization successful! You can close this window.</h2>"
                b"<p>Refresh token has been printed in your terminal.</p>"
                b"</body></html>"
            )
        elif "error" in qs:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Error: {qs['error'][0]}".encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging
        pass


def get_refresh_token(client_id: str, client_secret: str, port: int = 8080, no_browser: bool = False) -> dict:
    redirect_uri = f"http://localhost:{port}/"
    auth_url = build_auth_url(client_id, redirect_uri)

    print(f"\n1. Opening browser for authorization...")
    print(f"   If browser doesn't open, visit manually:\n   {auth_url}\n")
    print(f"2. Listening on {redirect_uri} for callback...\n")

    if not no_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass

    # Start server
    CallbackHandler.code = None
    with socketserver.TCPServer(("localhost", port), CallbackHandler) as httpd:
        # Wait for code with timeout
        def _wait():
            timeout = 120
            start = time.time()
            while CallbackHandler.code is None and time.time() - start < timeout:
                time.sleep(0.2)
            # Shutdown server
            try:
                httpd.shutdown()
            except Exception:
                pass

        t = threading.Thread(target=_wait, daemon=True)
        t.start()
        try:
            httpd.serve_forever()
        except Exception:
            pass
        t.join()

    if not CallbackHandler.code:
        print("No authorization code received within 120 seconds.")
        print("You can still do manual flow: copy the 'code' param from the redirect URL after authorization.")
        return {}

    print(f"Got authorization code: {CallbackHandler.code[:20]}...")

    try:
        tokens = exchange_code(client_id, client_secret, CallbackHandler.code, redirect_uri)
    except Exception as exc:
        print(f"Failed to exchange code: {exc}")
        return {}

    print("\n=== Tokens ===")
    print(f"Access Token (short-lived): {tokens.get('access_token','')[:30]}...")
    if "refresh_token" in tokens:
        print(f"\n*** REFRESH TOKEN (save this!) ***\n{tokens['refresh_token']}\n")
        print("Store this refresh_token in Ali OS → اتصال‌ها → Google Search Console / GA4")
    else:
        print("\nNo refresh_token returned — you may have already authorized this app before.")
        print("Go to https://myaccount.google.com/permissions and revoke access, then try again with prompt=consent.")
        print(f"Access token: {tokens}")

    return tokens


def main():
    parser = argparse.ArgumentParser(description="Get Google OAuth refresh token for Ali OS")
    parser.add_argument("--client-id", required=True, help="OAuth Client ID from Google Cloud Console")
    parser.add_argument("--client-secret", required=True, help="OAuth Client Secret")
    parser.add_argument("--port", type=int, default=8080, help="Local port for callback (default 8080)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    get_refresh_token(args.client_id, args.client_secret, port=args.port, no_browser=args.no_browser)


if __name__ == "__main__":
    main()
