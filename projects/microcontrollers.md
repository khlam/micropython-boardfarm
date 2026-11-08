# Microcontrollers

Compile and flash from inside a project: `cd projects/<project>`, then follow its README. Command summary: [projects/README.md](README.md#usage).

## Flashing

**RP2040-Zero / RP2350** — put the board in bootloader mode (below), then drag the `.uf2` onto the drive that appears. No serial bridge needed. Official guide: [Raspberry Pi — installing firmware](https://www.raspberrypi.com/documentation/microcontrollers/micropython.html#installing-micropython).

**ESP32-S3-Zero** — put the board in bootloader mode (below); the `esp32-flash` service writes over the serial port.

**ESP32-CAM** (Matter projects only) — seat it on its ESP32-CAM-MB programmer board and plug in USB; the `esp32cam-flash` service writes over the MB board's USB-serial bridge. The MB board enters the bootloader on its own.

The `viz` dashboard also reads the serial port. On macOS, Docker can't see USB devices, so do the [serial bridge setup](../tools/serial-bridge/serial-bridge.md#macos-serial-bridge) first.

## Bootloader mode

| Board | Enter | Appears as |
|---|---|---|
| RP2040-Zero | Hold **BOOT**, connect USB (or tap **RESET** while holding **BOOT**) | Drive `RPI-RP2` |
| RP2350 | Same | Drive `RP2350` |
| ESP32-S3-Zero | Hold **BOOT**, tap **RESET** (or hold **BOOT** while connecting USB) | `/dev/ttyACM0` |
| ESP32-CAM | Automatic on the ESP32-CAM-MB. If flashing fails to connect, hold **IO0**, tap **RST**, and retry | `/dev/ttyUSB0` |
