# Working notes

Things about this repo and this board that are not obvious from the code.

## Solved: joystick left/right did not move the mouse on QWERTY

**Symptom.** On QWERTY the joystick's left/right push moved the *text* cursor; on
NAV the same two switches moved the mouse pointer correctly.

**Cause.** ZMK Studio had a customised keymap saved in the keyboard's settings
partition. A stored keymap overrides the compiled one and survives a firmware
flash, so the board never ran the firmware we kept building. Connecting Studio
showed the joystick cluster as `<-` `Ret` `->` -- literal arrow keys and Enter --
while the compiled devicetree held `&mmv` / `&mkp` the whole time.

**Fix.** ZMK Studio -> device menu (top centre) -> **Restore Stock Settings**.
Confirmed working 2026-09-24.

Verified afterwards by selecting each key in Studio and reading the Behavior
panel, because Studio draws `&mmv` / `&mkp` as blank key caps:

| Position | Behavior | Value |
|---|---|---|
| Joystick up | `mouse_move` | 64336 (Y -1200) |
| Joystick down | `mouse_move` | 1200 (Y +1200) |
| Joystick left | `mouse_move` | 4216913920 (X -1200) |
| Joystick right | `mouse_move` | 78643200 (X +1200) |
| Joystick centre | Mouse Key Press | MB1, left click |
| Rotary push | Mouse Key Press | MB2, right click |

**The lesson worth keeping.** Five reflashes changed nothing and the compiled
devicetree verified correct every time, because the firmware was never what the
board was running. When ZMK behaviour disagrees with a verified keymap, suspect
stored settings before touching the keymap again.

Connecting Studio from browser automation needs
`navigator.serial.requestPort` patched to return the already-granted port from
`getPorts()`; the native port picker cannot be driven by a synthetic click.


## CI does not run on push

This repo is a fork of `a741725193/zmk-new_corne`, and GitHub disables workflows
on forks until someone enables them in the Actions tab. `on: push` never fires.
Dispatch manually:

    gh workflow run build.yml --ref main
    gh run watch <id> --exit-status

## Flashing on macOS 26

Copying a `.uf2` to `/Volumes/NICENANO` silently fails -- the FSKit msdos driver
buffers the write and the bootloader never sees it. Use serial DFU; see
`tools/flasher/`.

## This board has OLEDs, not nice!view

Both halves carry a 128x32 SSD1306 on I2C (addr 0x3c, SDA P0.17, SCL P0.20).
nice_view leaves `spi0` enabled, and the nRF52840 shares one peripheral between
spi0 and i2c0, so the panels never initialise -- the giveaway is a screen of
random pixels rather than a blank one. `build.yaml` uses `nice_oled` plus
`boards/shields/eyelash_corne/oled.dtsi`.
