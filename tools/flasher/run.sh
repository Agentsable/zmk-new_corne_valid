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
  # protobuf is for the ZMK update page (zmk_rpc + zmk_proto). Its version must
  # be >= the gencode in zmk_proto/, or the generated modules refuse to load.
  "$VENV/bin/pip" install -q adafruit-nrfutil 'protobuf>=7.36'
fi
mkdir -p "$PKG_DIR"

nohup "$VENV/bin/python" server.py >> server.log 2>&1 &
echo "flasher pid $! — http://127.0.0.1:8787"
