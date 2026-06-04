#!/bin/sh
# Bridge a USB-serial board to TCP so Docker can read AND flash it on macOS.
#
# Project-agnostic: it knows nothing about distance-stream / gyro-stream — it
# just exposes whatever board is plugged in on a TCP port. Run it once in its
# own terminal; then, with SERIAL_PORT exported (see AGENTS.md), every project's
# `docker compose up viz` and `docker compose run esp32-flash` work the same as
# on Linux.
#
# Why this exists: Docker Desktop runs containers inside a Linux VM, and neither
# it nor Apple's Virtualization.framework can pass a USB-serial device into that
# VM. So the `- /dev:/dev` mount the viz/esp32-flash services rely on is a no-op on
# macOS. This script reads/writes the board on the host and relays it over TCP;
# the containers connect with pyserial/esptool via
# socket://host.docker.internal:<port>, getting the same access Linux gets from
# native device passthrough. Built-in tools only (stty, cat, nc, mkfifo) —
# nothing is installed on the host.
#
# The relay is full-duplex: viz only reads, but esptool must also write, so a
# fifo carries device->client while nc's stdout carries client->device.
# Note: TCP carries no modem-control lines, so DTR/RTS auto-reset can't cross
# the bridge — flash with the board already in bootloader mode (hold BOOT, tap
# RESET); the esp32-flash stage passes --before/--after no_reset for socket:// ports.
#
# Env:
#   BRIDGE_TCP_PORT  TCP port to serve on    (default 5555)
#   BRIDGE_BAUD      serial baud rate        (default 115200; ignored by native
#                                             USB-CDC boards, which run at USB speed)
#   BRIDGE_DEVICE    explicit device path    (default: first board auto-detected)
#
# Loops forever: waits for the board, serves one client, and re-establishes on
# client disconnect, unplug, or reflash. Ctrl-C to stop.
set -eu

PORT="${BRIDGE_TCP_PORT:-5555}"
BAUD="${BRIDGE_BAUD:-115200}"

# macOS exposes USB-CDC boards (RP2040/RP2350/ESP32-S3) as /dev/cu.usbmodem*
# and FTDI/CP210x bridges as /dev/cu.usbserial*. Linux names are included so the
# script is usable there too, though Linux doesn't need it.
find_device() {
    if [ -n "${BRIDGE_DEVICE:-}" ]; then
        [ -e "$BRIDGE_DEVICE" ] && { printf '%s\n' "$BRIDGE_DEVICE"; return 0; }
        return 1
    fi
    for d in /dev/cu.usbmodem* /dev/cu.usbserial* /dev/ttyACM* /dev/ttyUSB*; do
        [ -e "$d" ] && { printf '%s\n' "$d"; return 0; }
    done
    return 1
}

# Raw 8N1 at BAUD. stty's device flag differs: BSD/macOS -f, GNU/Linux -F.
configure_line() {
    if [ "$(uname -s)" = "Darwin" ]; then
        stty -f "$1" "$BAUD" raw -echo
    else
        stty -F "$1" "$BAUD" raw -echo
    fi
}

# Listen for one TCP client and relay it to/from the device, full-duplex.
# BSD nc (macOS): `nc -l PORT`; GNU nc (Linux): `nc -l -p PORT`.
serve_once() {
    dev="$1"
    fifo="$(mktemp -u "${TMPDIR:-/tmp}/serial-bridge.XXXXXX")"
    mkfifo "$fifo"
    # nc: stdin (fifo = device output) -> client; client -> stdout (-> device).
    if [ "$(uname -s)" = "Darwin" ]; then
        nc -l "$PORT" > "$dev" < "$fifo" &
    else
        nc -l -p "$PORT" > "$dev" < "$fifo" &
    fi
    nc_pid=$!
    cat "$dev" > "$fifo" &
    cat_pid=$!
    # nc returns when the client disconnects; then stop the device reader so the
    # loop can re-establish (cat would otherwise block on an idle port).
    wait "$nc_pid" 2>/dev/null || true
    kill "$cat_pid" 2>/dev/null || true
    wait "$cat_pid" 2>/dev/null || true
    rm -f "$fifo"
}

echo "serial-bridge: serving on tcp/$PORT (clients use socket://host.docker.internal:$PORT)"
while true; do
    dev="$(find_device || true)"
    if [ -z "$dev" ]; then
        sleep 1
        continue
    fi
    # A reflash/unplug between detection and use is routine; swallow the error
    # and retry rather than letting `set -e` kill the bridge.
    configure_line "$dev" 2>/dev/null || { sleep 1; continue; }
    echo "serial-bridge: $dev <-> tcp/$PORT"
    serve_once "$dev" 2>/dev/null || true
    sleep 1
done
