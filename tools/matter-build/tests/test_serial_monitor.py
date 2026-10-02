"""Host tests for the serial capture window: reopening, sending, and reads.

_capture is exercised against a fake serial.Serial rather than a real device:
the behavior under test only shows up when a port vanishes mid-write or
mid-read, which a real board can't be made to do on demand, but a fake stood
in for serial_monitor's own `serial.Serial` calls can.
"""

import argparse
import time

import serial
import serial_monitor

_WINDOW_S = 0.05


def test_capture_retries_a_send_that_drops_mid_write(tmp_path, monkeypatch, capsys):
    port_path = tmp_path / "ttyFAKE"
    port_path.touch()
    connections: list[_FakePort] = []

    def open_port(path, baud, timeout):
        assert path == str(port_path)
        port = _FakePort(fail_write=(len(connections) == 0))
        connections.append(port)
        return port

    monkeypatch.setattr(serial_monitor.serial, "Serial", open_port)
    args = argparse.Namespace(
        port=str(port_path), baud=115200, send="print('hi')", interrupt=False, probe=False
    )
    started = time.monotonic()

    serial_monitor._capture(args, started, started + _WINDOW_S)

    assert len(connections) == 2
    # The port vanished before the write landed -- nothing was recorded.
    assert connections[0].writes == []
    # The keystrokes were never delivered, so the reopened connection retries them.
    assert connections[1].writes == [b"print('hi')\r\n"]
    assert connections[0].closed
    assert connections[1].closed
    assert "-- serial link dropped, reopening --" in capsys.readouterr().out


def test_capture_does_not_resend_after_a_later_read_drops(tmp_path, monkeypatch):
    port_path = tmp_path / "ttyFAKE"
    port_path.touch()
    connections: list[_FakePort] = []

    def open_port(path, baud, timeout):
        port = _FakePort(fail_write=False, fail_read=(len(connections) == 0))
        connections.append(port)
        return port

    monkeypatch.setattr(serial_monitor.serial, "Serial", open_port)
    args = argparse.Namespace(
        port=str(port_path), baud=115200, send="print('hi')", interrupt=False, probe=False
    )
    started = time.monotonic()

    serial_monitor._capture(args, started, started + _WINDOW_S)

    assert len(connections) == 2
    # The send landed on the first connection...
    assert connections[0].writes == [b"print('hi')\r\n"]
    # ...so the reconnect the dropped read triggers must not resend it.
    assert connections[1].writes == []


class _FakePort:
    """Minimal serial.Serial stand-in: only the API surface _capture touches."""

    def __init__(self, *, fail_write: bool, fail_read: bool = False) -> None:
        self._fail_write = fail_write
        self._fail_read = fail_read
        self.writes: list[bytes] = []
        self.closed = False

    def __enter__(self) -> "_FakePort":
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True

    def write(self, data: bytes) -> None:
        if self._fail_write:
            raise serial.SerialException("port vanished mid-write")
        self.writes.append(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        if self._fail_read:
            self._fail_read = False
            raise serial.SerialException("port vanished mid-read")
        return b""
