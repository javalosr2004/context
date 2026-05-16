#!/usr/bin/env bash
set -euo pipefail

export HF_HOME=/workspace/.cache/huggingface
export TRANSFORMERS_CACHE=/workspace/.cache/huggingface

cd /app

exec uvicorn server:app --host 0.0.0.0 --port 8000
