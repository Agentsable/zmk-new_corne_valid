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


## The west module shadows this repo's shield

`config/west.yml` pulls `a741725193/zmk-new_corne` as a module, and that module
ships a **duplicate copy of this board's shield**. Locally the module's copy
wins, so edits to `boards/shields/eyelash_corne/*.overlay` in this repo have no
effect on a local build. Check which file dtc actually read:

    grep -oE "/workspace[^ :]*eyelash_corne_right.overlay" build/right_nice/zephyr/zephyr.dts.d

If that prints `/workspace/eyelash_corne/boards/...`, the module won.

**Do not remove the module from west.yml to fix this.** It was tried: both halves
then fail to configure, because this repo's `zephyr/module.yml` (which declares
`board_root: .`) sits underneath west's own 552 MB Zephyr checkout at the same
path and never registers. The shield comes *only* from that module.

So the display node reaches the build two different ways, on purpose:

| Environment | Mechanism |
|---|---|
| CI | `#include "oled.dtsi"` in the shield overlay -- nothing shadows it there |
| Local | `-DEXTRA_DTC_OVERLAY_FILE=.../oled.dtsi` passed by the flasher |

`oled.dtsi` carries a `#pragma once`, so both applying at once is harmless.

**Symptom if this breaks:** the right half fails with
`'__device_dts_ord_DT_CHOSEN_zephyr_display_ORD' undeclared`. That means
`CONFIG_ZMK_DISPLAY=y` (from the nice_oled shield) but no display node in the
devicetree. Confirm with `grep -c ssd1306@3c build/<side>_nice/zephyr/zephyr.dts`
-- it should be 1.

## Fresh build directories need west zephyr-export

A build directory with no CMake cache cannot resolve the Zephyr CMake package:

    CMake Error at CMakeLists.txt:9 (find_package):
      Could not find a package configuration file provided by "Zephyr"

The container has no CMake package registry. Run `west zephyr-export` first;
`build_halves()` in the flasher does this. Incremental builds only worked because
their cache already held `Zephyr_DIR`, which is why this stayed hidden until a
build directory got wiped.

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
