# Corne flasher

Local deploy tool for this keyboard: renders the keymap from source, flashes both
halves over serial DFU, and tags each release in git.

    ./run.sh                      # http://127.0.0.1:8787
    ./deploy.py "version name"    # same workflow, from the terminal

Requires Docker (for `west build`) and `adafruit-nrfutil` in a venv; `run.sh`
points `NRFUTIL` and `PKG_DIR` at them.

## Why this exists

macOS 26 mounts the bootloader volume with the FSKit msdos driver, which buffers
writes so the UF2 bootloader never sees them. Drag-flashing a `.uf2` onto
`/Volumes/NICENANO` silently fails. Serial DFU is the working path.

## Pages

| Page | Purpose |
|---|---|
| Firmware update | Name a version and run the deploy workflow |
| Current keymap | What the board is running, from the committed keymap |
| Update request | Pending change; keys are editable, saving opens a request |
| Source verification | Re-reads the firmware sources and checks the render against them |

## Workflow

1. Commit + tag + push `predeploy_<dd-mm-yy_hh-mm>_<name>`
2. Build both halves in Docker and repackage for DFU
3. Flash **right**, then **left** (double-tap reset on each when it turns red)
4. Tag + push `deployed_<dd-mm-yy_hh-mm>_<name>`

## Notes for whoever picks this up

- Everything rendered is derived from `boards/shields/eyelash_corne/*.dtsi` and
  `config/eyelash_corne.keymap`. `layout.py` finds the joystick by locating a
  matrix column whose five keys form a plus; nothing is indexed by hand. The
  Source verification page proves this on demand.
- `adafruit-nrfutil` **exits 0 even when a flash fails**. Success requires its
  `Device programmed.` line -- see `flash()` in `server.py`.
- A new serial port is *not* proof of DFU. The NICENANO volume is required, or a
  board still running its firmware gets flashed and dies mid-write.
- ZMK ignores the 1200-baud touch reset, so the physical double-tap cannot be
  automated away. Binding `&bootloader` to a combo would remove it for good.

Run the self-check with `python3 test_detect.py`.
