#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}"
  echo "Create it from .env.example and set HAI_API_KEY before starting gui-grounding."
  exit 1
fi

cd "${SCRIPT_DIR}"

if [[ ! -x ".venv/bin/python" ]]; then
  uv venv .venv
fi

uv pip install --python .venv/bin/python -r requirements.txt

exec .venv/bin/python -m uvicorn app:app \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8080}" \
  --reload \
  --reload_excludes tests \ 
  --env-file "${ENV_FILE}"
