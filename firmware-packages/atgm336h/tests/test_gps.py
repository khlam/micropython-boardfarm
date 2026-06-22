"""Tests for atgm336h: NMEA line parsing, UART open, and the presence probe."""

import machine
import pytest

from atgm336h import GPS, DeviceNotFoundError

_GPRMC = b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n"
_GPGGA = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"
_GPGSV = b"$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75\r\n"


def _make_gps(uart_lines):
    """Create a GPS instance with pre-fed UART data (first line consumed by probe)."""
    machine.reset()
    machine.feed_uart(uart_lines)
    return GPS(bus_id=0, tx=0, rx=1)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        (b"junk data\r\n", None),
        (b"\r\n", None),
        (b"\xff\xfe\r\n", None),
        (_GPRMC, _GPRMC.decode().strip()),
        (_GPGGA, _GPGGA.decode().strip()),
        (_GPGSV, _GPGSV.decode().strip()),
    ],
)
def test_readline_parses(raw, expected):
    """readline() decodes, strips, and validates the NMEA ``$`` prefix."""
    probe_line = [_GPRMC]
    data_line = [] if raw is None else [raw]
    gps = _make_gps(probe_line + data_line)
    assert gps.readline() == expected


def test_gps_probe_raises_device_not_found_on_quiet_line():
    """No bytes within the probe budget → DeviceNotFoundError (probe_ms=0 = one pass)."""
    machine.reset()
    with pytest.raises(DeviceNotFoundError):
        GPS(bus_id=0, tx=0, rx=1, probe_ms=0)


def test_gps_readline_streams_after_probe():
    """The probe consumes the first line; readline() yields the next parsed one."""
    gps = _make_gps([_GPRMC, _GPGGA])
    assert gps.readline().startswith("$GPGGA")
    assert gps.readline() is None
