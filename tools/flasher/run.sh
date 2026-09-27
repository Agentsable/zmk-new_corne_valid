#!/bin/sh
# Launch the flasher. Self-contained: creates its own venv and package dir on
# first run, so the tool keeps working after any scratch directory is cleaned up.
set -e
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
export PKG_DIR="${PKG_DIR:-$PWD/pkg}"
export NRFUTIL="${NRFUTIL:-$PWD/$VENV/bin/adafruit-nrfutil}"

if [ ! -x "$NRFUTIL" ]; then
  echo "setting up $VENV (first run)…"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q adafruit-nrfutil
fi
mkdir -p "$PKG_DIR"

nohup python3 server.py >> server.log 2>&1 &
echo "flasher pid $! — http://127.0.0.1:8787"
