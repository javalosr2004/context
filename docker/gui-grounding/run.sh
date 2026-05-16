#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/uvicorn" ]; then
  uv venv
  uv pip install -r requirements.txt
fi

exec .venv/bin/uvicorn app:app --host 0.0.0.0 --port "${PORT:-8080}"
