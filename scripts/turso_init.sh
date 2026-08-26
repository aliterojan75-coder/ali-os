#!/usr/bin/env bash
# Convenience wrapper: python -m scripts.turso_init
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m scripts.turso_init
