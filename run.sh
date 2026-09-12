#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python -m pip install -r requirements.txt --quiet
echo "ArchiMind running at http://localhost:${PORT:-8000}"
python -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
