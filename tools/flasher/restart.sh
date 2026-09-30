#!/bin/sh
# Restart the flasher. Kills by LISTENING PORT, not by process name: the macOS
# framework binary is "Python server.py" with a capital P, so `pkill -f "python
# server.py"` matches nothing and silently leaves the old code serving.
set -e
cd "$(dirname "$0")"
pid=$(lsof -nP -tiTCP:${FLASHER_PORT:-8787} -sTCP:LISTEN 2>/dev/null || true)
[ -n "$pid" ] && { kill $pid; sleep 1.5; }
exec ./run.sh
