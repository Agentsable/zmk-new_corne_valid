# Working notes

Things about this repo and this board that are not obvious from the code.

## Open: joystick left/right do not move the mouse on QWERTY

**Symptom.** On the QWERTY layer the joystick's left/right push moves the *text*
cursor. On NAV the same two switches move the mouse pointer correctly.

**What has been ruled out.**

- Not the keymap. Positions 19 and 21 hold `&mmv MOVE_LEFT` / `&mmv MOVE_RIGHT`,
  verified in the compiled devicetree (`build/left_nice/zephyr/zephyr.dts`) on
  every build. The Source verification page traces all 192 bindings back to
  `config/eyelash_corne.keymap`.
- Not the position mapping. `tools/flasher/layout.py` derives the joystick from
  the matrix transform by finding the column whose five keys form a plus. It
  independently produces the same indices: 6=up, 19=left, 20=centre, 21=right,
  35=down, all on column 12; rotary at index 34 / `RC(3,2)`.
- Not the speed. Tried 2400, then 1200, then 600. NAV works at every value
  tested; QWERTY fails at every value tested. The layer is the variable, not the
  magnitude.
- Not an axis bug. `&mmv` packs X and Y into one 32-bit value, decodes both in
  one function, and emits them in one HID report. No code path moves Y but not X.

**Leading hypothesis: ZMK Studio is overriding layer 0 at runtime.**
`CONFIG_ZMK_STUDIO`, `CONFIG_SETTINGS` and `CONFIG_ZMK_SETTINGS_RPC` are all
enabled, so Studio writes keymap edits into the settings partition. Those
override the compiled keymap and survive a firmware flash, which fits every
observation: the devicetree keeps verifying correct, NAV is untouched, and five
reflashes changed nothing.

**To confirm or kill it:**

1. Open ZMK Studio and restore/reset the keymap to the firmware default. If the
   pointer then moves on QWERTY, that was it.
2. Otherwise flash the `settings_reset` shield to the left half and reflash.
   CI builds it (`build.yaml`); a local build of it currently fails to resolve
   the Zephyr CMake package in a fresh build directory.
3. If neither helps, bind positions 19 and 21 to visible letters on a spare
   layer and see whether the switches register at all.

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
