"""Tests for atgm336h: NMEA line parsing, UART open, and the presence probe."""

import machine
import pytest
import utime

from atgm336h import GPS, DeviceNotFoundError

_GPRMC = b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n"
_GPGGA = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"
_GPGSV = b"$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75\r\n"


@pytest.mark.parametrize(
    "raw,expected",
    [(None, None), (_GPRMC, _GPRMC.decode().strip())],
    ids=["nothing-buffered", "complete-sentence"],
)
def test_readline_returns_a_stripped_sentence_or_none(raw, expected):
    """readline() decodes and strips a buffered line, or reports nothing ready.

    The rejection cases live in ``test_bad_line_does_not_discard_following_sentence``,
    which asserts the same ``None`` *and* that the next sentence still survives.
    """
    probe_line = [_GPRMC]
    data_line = [] if raw is None else [raw]
    gps = _make_gps(probe_line + data_line)
    assert gps.readline() == expected


def test_gps_probe_raises_device_not_found_on_quiet_line():
    """A zero probe budget immediately reports an unavailable receiver."""
    machine.reset()
    with pytest.raises(DeviceNotFoundError):
        GPS(bus_id=0, tx=0, rx=1, probe_ms=0)


def test_uart_opens_on_the_requested_bus_at_the_modules_fixed_baud():
    """The ATGM336H only ever talks 9600 8N1, and a TX/RX swap reads nothing.

    Neither shows up as a test failure anywhere else — a wrong baud rate or a
    swapped pin pair simply produces a silent line, which is indistinguishable
    from an unplugged module.
    """
    _make_gps([_GPRMC])
    uart = machine.uart_constructions[-1]

    # Read through `config`, not the attributes: the stub defaults baudrate to
    # 9600 and timeout to 0, so an omitted keyword would still read correct.
    assert uart.id == 0
    assert uart.config["baudrate"] == 9600
    assert (uart.config["tx"].id, uart.config["rx"].id) == (0, 1)
    # Non-blocking: a blocking read would stall the cooperative display loop.
    assert uart.config["timeout"] == 0


def test_gps_readline_streams_after_probe():
    """The probe consumes the first line; readline() yields the next parsed one."""
    gps = _make_gps([_GPRMC, _GPGGA])
    assert gps.readline().startswith("$GPGGA")
    assert gps.readline() is None


def test_probe_waits_for_fragmented_leading_line_and_keeps_following_sentence(monkeypatch):
    machine.reset()
    machine.feed_uart_bytes(b"tail of a sentence")
    clock = [0]
    sleeps = []
    monkeypatch.setattr(utime, "ticks_ms", lambda: clock[0])

    def receive_on_sleep(ms):
        sleeps.append(ms)
        clock[0] += ms
        machine.feed_uart_bytes(b"\r\n" + _GPGGA)

    monkeypatch.setattr(utime, "sleep_ms", receive_on_sleep)
    gps = GPS(bus_id=0, tx=0, rx=1, probe_ms=100)
    # One poll: the fragment completes on the first sleep, so the probe returns.
    assert sleeps == [10]
    assert gps.readline() == _GPGGA.decode().strip()
    assert gps.readline() is None


@pytest.mark.parametrize("initial_bytes", [b"", b"$GPRMC,unfinished"])
def test_probe_times_out_without_complete_line(monkeypatch, initial_bytes):
    machine.reset()
    machine.feed_uart_bytes(initial_bytes)
    clock = [0]
    sleeps = []
    monkeypatch.setattr(utime, "ticks_ms", lambda: clock[0])

    def advance(ms):
        sleeps.append(ms)
        clock[0] += ms

    monkeypatch.setattr(utime, "sleep_ms", advance)
    with pytest.raises(DeviceNotFoundError, match="100 ms"):
        GPS(bus_id=0, tx=0, rx=1, probe_ms=100)
    assert clock[0] >= 100
    assert sleeps and all(ms >= 10 for ms in sleeps)


@pytest.mark.parametrize("chunk_size", [1, 20, len(_GPGGA) - 1])
def test_gps_assembles_fragments_and_keeps_the_next_partial_sentence(chunk_size):
    gps = _make_gps([_GPRMC])
    for start in range(0, len(_GPGGA) - 1, chunk_size):
        machine.feed_uart_bytes(_GPGGA[start : min(start + chunk_size, len(_GPGGA) - 1)])
        assert gps.readline() is None
        assert gps.readline() is None

    machine.feed_uart_bytes(_GPGGA[-1:] + _GPGSV[:20])
    assert gps.readline() == _GPGGA.decode().strip()
    assert gps.readline() is None
    machine.feed_uart_bytes(_GPGSV[20:] + _GPRMC)
    assert gps.readline() == _GPGSV.decode().strip()
    assert gps.readline() == _GPRMC.decode().strip()
    assert gps.readline() is None


@pytest.mark.parametrize("bad_line", [b"\xff\xfe\r\n", b"noise\r\n", b"\r\n"])
def test_bad_line_does_not_discard_following_sentence(bad_line):
    gps = _make_gps([_GPRMC])
    machine.feed_uart_bytes(bad_line + _GPGGA)
    assert gps.readline() is None
    assert gps.readline() == _GPGGA.decode().strip()


def test_uart_failure_preserves_partial_sentence_for_retry(monkeypatch):
    gps = _make_gps([_GPRMC])
    machine.feed_uart_bytes(_GPGGA[:20])
    assert gps.readline() is None
    machine.feed_uart_bytes(_GPGGA[20:])

    def fail_read(_uart, _count):
        raise OSError("UART unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(machine.UART, "read", fail_read)
        with pytest.raises(OSError, match="UART unavailable"):
            gps.readline()

    assert gps.readline() == _GPGGA.decode().strip()


def _make_gps(uart_lines):
    """Create a GPS instance with pre-fed UART data (first line consumed by probe)."""
    machine.reset()
    machine.feed_uart(uart_lines)
    return GPS(bus_id=0, tx=0, rx=1)
