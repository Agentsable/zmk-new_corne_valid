#!/bin/sh
# Start the local flasher and attach it to the hosted app at keys.hyperdev.app.
#
# This is what the hosted page hands you when its indicator is red. Safe to run
# twice: it reuses an already-running server instead of starting a second one.
set -e
cd "$(dirname "$0")"

TOKEN_FILE="${TUNNEL_TOKEN_FILE:-$PWD/.tunnel-token}"
if [ ! -f "$TOKEN_FILE" ]; then
  echo "No tunnel credential at $TOKEN_FILE."
  echo "Recreate it with:  cloudflared tunnel token keys-local > $TOKEN_FILE"
  exit 1
fi

if curl -sf -o /dev/null --max-time 3 http://127.0.0.1:8787/api/state; then
  echo "local flasher already running on 8787"
else
  ./run.sh
fi

echo "connecting tunnel keys-local -- leave this window open, Ctrl-C disconnects"
exec cloudflared tunnel run --token "$(cat "$TOKEN_FILE")"
