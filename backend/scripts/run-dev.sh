#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${BACKEND_DIR}/.." && pwd)"
ENV_FILE="${BACKEND_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}"
  echo "Create it with GEMINI_API_KEY and optional GEMINI_MODEL before starting the backend."
  exit 1
fi

cd "${REPO_ROOT}"

exec uv run --project backend uvicorn backend.main:app \
  --host "${HOST:-127.0.0.1}" \
  --port "${PORT:-8000}" \
  --reload \
  --env-file "${ENV_FILE}"
