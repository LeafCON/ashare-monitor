#!/bin/bash
# Portfolio Monitor — Start script
# Usage: bash start.sh [--port 8802]

set -e

cd "$(dirname "$0")"
PORT="${1:-8802}"

echo "📊 Portfolio Monitor"
echo "===================="
echo "Starting on port $PORT ..."
echo ""

# Activate venv if exists
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Run
cd backend
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
