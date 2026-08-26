#!/usr/bin/env bash
# Open a public HTTPS tunnel to the local gunicorn server using pinggy.io
# (free tier expires after 60 minutes — fine for development).
#
# Usage:
#   ./scripts/tunnel.sh
#
# After it prints a https://*.run.pinggy-free.link URL, put it in .env as
# PUBLIC_URL and register the Telegram webhook:
#   python -m app.tools.set_webhook

set -euo pipefail
PORT="${PORT:-8080}"
echo "Opening tunnel to localhost:${PORT} ..."
exec ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
  -R 80:localhost:${PORT} -p 443 a.pinggy.io
