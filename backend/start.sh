#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -f ".venv/bin/activate" ] && source .venv/bin/activate
[ ! -f ".env" ] && cp .env.example .env && echo "⚠  Edit .env before production use"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --log-level info
