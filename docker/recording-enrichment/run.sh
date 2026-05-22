#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$PWD/src"
exec uv run uvicorn recording_enrichment.app:app --host 0.0.0.0 --port 8000 --reload "$@"
