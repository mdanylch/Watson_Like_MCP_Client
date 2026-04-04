#!/bin/sh
# App Runner (Python 3.11): install deps at runtime, then uvicorn.
# This app requires `codex` on PATH — use the repo Dockerfile or install @openai/codex in the image.
set -e
pip3 install --no-cache-dir -r requirements.txt
PORT="${PORT:-8080}"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
