#!/bin/sh
# App Runner (Python 3.11): same pattern as webex-cc-mcp — install at runtime so deps
# land in the run image; then start uvicorn.
set -e
pip3 install --no-cache-dir -r requirements.txt
PORT="${PORT:-8080}"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
