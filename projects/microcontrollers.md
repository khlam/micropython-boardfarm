# Microcontrollers

## Compile & flash
Compile and flash run **per project** — `cd projects/<project>` first, then follow that project's README, which carries the full step-by-step for every board alongside its dashboard and wiring. The command summary lives in [projects/README.md](README.md#usage).

> RP2040 / RP2350 firmware flashes by drag-copying a UF2 onto the mounted bootloader drive, so it needs no serial bridge — only the `esp32-flash` service and the `viz` dashboard use the serial port. **On macOS, do the [serial bridge setup](../tools/serial-bridge/serial-bridge.md#macos-serial-bridge) first** — Docker can't see USB devices there.

## Bootloader mode
Put the board in bootloader mode before flashing.

| Board | How | Result |
|---|---|---|
| RP2040-Zero | Hold **BOOT** and connect USB (or tap **RESET** while holding **BOOT**) | Mounts as USB drive `RPI-RP2` — drag the UF2 onto it |
| RP2350 | Hold **BOOT** and connect USB (or tap **RESET** while holding **BOOT**) | Mounts as USB drive `RP2350` — drag the UF2 onto it |
| ESP32-S3-Zero | Hold **BOOT** and tap **RESET**, or hold **BOOT** and connect USB | Appears as `/dev/ttyACM0`; the `esp32-flash` service fails fast if the node is missing |
