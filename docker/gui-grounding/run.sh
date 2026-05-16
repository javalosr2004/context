#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  uv venv .venv
fi

uv pip install --python .venv/bin/python -r requirements.txt

exec .venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-8080}"
