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

RELOAD=0
for arg in "$@"; do
  case "${arg}" in
    --reload)
      RELOAD=1
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      exit 2
      ;;
  esac
done

cd "${REPO_ROOT}"

if [[ "${RELOAD}" -eq 1 ]]; then
  exec uv run --project backend uvicorn backend.main:app \
    --host "${HOST:-127.0.0.1}" \
    --port "${PORT:-8000}" \
    --reload \
    --env-file "${ENV_FILE}"
else
  exec uv run --project backend uvicorn backend.main:app \
    --host "${HOST:-127.0.0.1}" \
    --port "${PORT:-8000}" \
    --env-file "${ENV_FILE}"
fi
