#!/bin/bash
# Portfolio Monitor — Run in background
set -e
cd "$(dirname "$0")"

PORT="${1:-8802}"
PIDFILE="data/.server.pid"
LOGFILE="data/server.log"

# Check if already running
if [ -f "$PIDFILE" ] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; then
    echo "⚠️  Already running (PID $(cat $PIDFILE))"
    echo "   Use ./stop.sh to stop first"
    exit 1
fi

# Activate venv
source venv/bin/activate

echo "📊 Portfolio Monitor starting on port $PORT ..."
cd backend
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" > "../$LOGFILE" 2>&1 &
PID=$!
cd ..
echo "$PID" > "$PIDFILE"
echo "✅ Started (PID $PID)"
echo "   Web UI: http://localhost:$PORT"
echo "   Logs:   tail -f $LOGFILE"
