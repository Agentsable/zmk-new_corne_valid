#!/bin/sh
# Launch the flasher UI. Points at the venv nrfutil and the built DFU packages.
export NRFUTIL="${NRFUTIL:-/private/tmp/claude-501/-Users-yigalweinberger-Documents-Code-home-code-keyborads-zmk-new-corne-valid/2d804b23-36a0-469d-89e3-fe057568a13d/scratchpad/dfu/bin/adafruit-nrfutil}"
export PKG_DIR="${PKG_DIR:-/private/tmp/claude-501/-Users-yigalweinberger-Documents-Code-home-code-keyborads-zmk-new-corne-valid/2d804b23-36a0-469d-89e3-fe057568a13d/scratchpad}"
exec python3 "$(dirname "$0")/server.py"
