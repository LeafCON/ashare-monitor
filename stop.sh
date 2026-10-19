#!/bin/bash
# Portfolio Monitor — Stop server
cd "$(dirname "$0")"

PIDFILE="data/.server.pid"

if [ ! -f "$PIDFILE" ]; then
    echo "⚠️  No PID file found. Server not running?"
    exit 0
fi

PID=$(cat "$PIDFILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "✅ Stopped (PID $PID)"
else
    echo "⚠️  Process $PID not running"
fi
rm -f "$PIDFILE"
