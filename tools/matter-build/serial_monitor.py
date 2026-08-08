"""Stream an ESP32-S3's serial output as timestamped lines.

The firmware writes one JSON object per line, so lines are passed through
verbatim rather than parsed: a MicroPython traceback or a raw ESP-IDF log is
exactly the evidence wanted when the question is why a firmware loop stopped
running, and decoding the stream would discard it. The leading elapsed time
makes a periodic emission's cadence readable at a glance.

Boards whose console is the USB-serial-JTAG peripheral drop off the USB bus
while they reboot, so the capture reopens the device rather than treating a
vanished port as the end of the run.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import serial

_DEFAULT_BAUD = 115200
_DEFAULT_SECONDS = 90.0
_READ_TIMEOUT_S = 0.2
_REOPEN_POLL_S = 0.2
_RESET_HOLD_S = 0.1


def main() -> int:
    """Capture serial output for a bounded window and return an exit status."""
    args = _parse_args()
    started = time.monotonic()
    deadline = started + args.seconds
    if args.reset:
        _pulse_reset(args.port, args.baud)
    _capture(args, started, deadline)
    return 0


def _parse_args() -> argparse.Namespace:
    """Parse the monitor's command line."""
    parser = argparse.ArgumentParser(description="Capture ESP32-S3 serial output.")
    parser.add_argument("--port", required=True, help="serial device to read")
    parser.add_argument("--baud", type=int, default=_DEFAULT_BAUD, help="serial line speed")
    parser.add_argument(
        "--seconds", type=float, default=_DEFAULT_SECONDS, help="capture window before exiting"
    )
    parser.add_argument(
        "--no-reset",
        dest="reset",
        action="store_false",
        help="capture the running board instead of restarting it first",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="send a newline on connect; a REPL prompt in the reply means no script is running",
    )
    parser.add_argument(
        "--send",
        default="",
        help="run this line on the board's REPL once, on the first connection",
    )
    parser.add_argument(
        "--interrupt",
        action="store_true",
        help="send Ctrl-C first, stopping any running program so the REPL can accept input",
    )
    return parser.parse_args()


def _pulse_reset(path: str, baud: int) -> None:
    """Restart the board so the capture includes its boot output.

    Pulls EN low through RTS while holding GPIO0 high through DTR, which
    restarts the application rather than entering the serial bootloader. A USB
    bridge that ignores the modem control lines needs the board's reset button
    pressed instead, so this is best-effort by design.
    """
    with serial.Serial(path, baud, timeout=_READ_TIMEOUT_S) as port:
        port.dtr = False
        port.rts = True
        time.sleep(_RESET_HOLD_S)
        port.reset_input_buffer()
        port.rts = False


def _capture(args: argparse.Namespace, started: float, deadline: float) -> None:
    """Read the device until the window closes, reopening across reboots."""
    # Only the first connection gets the keystrokes: a command that reboots the
    # board would otherwise fire again on every reconnect it causes.
    pending = args.interrupt or args.probe or bool(args.send)
    while time.monotonic() < deadline:
        port = _open(args.port, args.baud, deadline)
        if port is None:
            _write(started, "-- no serial device appeared before the capture window closed --")
            return
        with port:
            if pending:
                _send(port, args.send, interrupt=args.interrupt)
                pending = False
            try:
                _read_lines(port, started, deadline)
            except serial.SerialException:
                _write(started, "-- serial link dropped, reopening --")


def _send(port: serial.Serial, line: str, *, interrupt: bool) -> None:
    """Type one line at the board's REPL.

    A board running a program has no REPL to type at and ignores the input,
    which is the safe outcome: the interrupt that would make it listen also
    stops the program, so it stays opt-in rather than firing on every capture.
    """
    if interrupt:
        port.write(b"\x03")
        port.flush()
        time.sleep(_RESET_HOLD_S)
    port.write(line.encode("utf-8") + b"\r\n")
    port.flush()


def _open(path: str, baud: int, deadline: float) -> serial.Serial | None:
    """Return an open port once the device node exists, or None past the deadline."""
    while time.monotonic() < deadline:
        if Path(path).exists():
            try:
                return serial.Serial(path, baud, timeout=_READ_TIMEOUT_S)
            except serial.SerialException:
                pass
        time.sleep(_REOPEN_POLL_S)
    return None


def _read_lines(port: serial.Serial, started: float, deadline: float) -> None:
    """Write every received line to stdout until the capture window closes."""
    while time.monotonic() < deadline:
        raw = port.readline()
        if raw:
            _write(started, raw.decode("utf-8", errors="replace").rstrip("\r\n"))


def _write(started: float, line: str) -> None:
    """Emit one capture line stamped with its offset from the capture start."""
    sys.stdout.write(f"[{time.monotonic() - started:7.2f}] {line}\n")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
