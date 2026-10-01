#!/usr/bin/env bash
# setup_api_service.sh — provision and launch the nlp-enrich FastAPI service.
#
# Mirrors the page-classification reference: create a venv, install the repo +
# service requirements, then start uvicorn. (Until 0.23.0 it also prefetched the
# KeyBERT model; keywords moved to atrium-keyword-extract.)
#
# Usage:
#   ./setup_api_service.sh            # install + launch on ${PORT:-8000}
#   ./setup_api_service.sh --no-serve # install only
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-$HERE/venv-nlp}"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo "[setup] venv: $VENV"
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

pip install --upgrade pip
pip install -r "$HERE/requirements.txt"
pip install -r "$HERE/service/requirements.txt"

if [ "${1:-}" = "--no-serve" ]; then
    echo "[setup] install complete (--no-serve)."
    exit 0
fi

echo "[setup] launching: uvicorn service.api:app --host $HOST --port $PORT"
exec uvicorn service.api:app --host "$HOST" --port "$PORT"
