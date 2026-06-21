"""Tests for atgm336h: NMEA line parsing, UART open, and the presence probe."""

import machine
import pytest

from atgm336h import GPS, DeviceNotFoundError, _parse_line

_GPRMC = b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n"
_GPGGA = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"
_GPGSV = b"$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75\r\n"


def test_parse_line_none_when_no_data():
    assert _parse_line(None) is None


def test_parse_line_returns_gprmc():
    assert _parse_line(_GPRMC).startswith("$GPRMC")


def test_parse_line_returns_gpgga():
    assert _parse_line(_GPGGA).startswith("$GPGGA")


def test_parse_line_strips_crlf():
    result = _parse_line(_GPRMC)
    assert not result.endswith("\r\n")
    assert not result.endswith("\n")


def test_parse_line_filters_non_nmea_line():
    assert _parse_line(b"junk data\r\n") is None


def test_parse_line_filters_empty_line():
    assert _parse_line(b"\r\n") is None


def test_parse_line_handles_decode_error():
    assert _parse_line(b"\xff\xfe\r\n") is None


@pytest.mark.parametrize("raw", [_GPRMC, _GPGGA, _GPGSV])
def test_parse_line_accepts_standard_nmea_sentences(raw: bytes):
    assert _parse_line(raw).startswith("$")


def test_gps_opens_uart_on_wired_pins():
    machine.feed_uart([_GPRMC])
    gps = GPS(bus_id=1, tx=17, rx=18)
    assert gps._uart.id == 1
    assert gps._uart.tx.id == 17
    assert gps._uart.rx.id == 18


def test_gps_probe_raises_device_not_found_on_quiet_line():
    """No bytes within the probe budget → DeviceNotFoundError (probe_ms=0 = one pass)."""
    with pytest.raises(DeviceNotFoundError):
        GPS(bus_id=0, tx=0, rx=1, probe_ms=0)


def test_gps_readline_streams_after_probe():
    """The probe consumes the first line; readline() yields the next parsed one."""
    machine.feed_uart([_GPRMC, _GPGGA])
    gps = GPS(bus_id=0, tx=0, rx=1)
    assert gps.readline().startswith("$GPGGA")
    assert gps.readline() is None
