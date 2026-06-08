"""Tests for atgm336h.GPS readline() behaviour using a FakeUART."""

import pytest
from fake_uart import FakeUART

from atgm336h.atgm336h import GPS

_GPRMC = b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n"
_GPGGA = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"


def test_readline_none_when_no_data():
    gps = GPS(FakeUART([]))
    assert gps.readline() is None


def test_readline_returns_gprmc():
    gps = GPS(FakeUART([_GPRMC]))
    result = gps.readline()
    assert result is not None
    assert result.startswith("$GPRMC")


def test_readline_returns_gpgga():
    gps = GPS(FakeUART([_GPGGA]))
    result = gps.readline()
    assert result is not None
    assert result.startswith("$GPGGA")


def test_readline_strips_crlf():
    gps = GPS(FakeUART([_GPRMC]))
    result = gps.readline()
    assert result is not None
    assert not result.endswith("\r\n")
    assert not result.endswith("\n")


def test_readline_filters_non_nmea_line():
    gps = GPS(FakeUART([b"junk data\r\n"]))
    assert gps.readline() is None


def test_readline_filters_empty_line():
    gps = GPS(FakeUART([b"\r\n"]))
    assert gps.readline() is None


def test_readline_handles_decode_error():
    gps = GPS(FakeUART([b"\xff\xfe\r\n"]))
    assert gps.readline() is None


def test_readline_drains_queue_in_order():
    gps = GPS(FakeUART([_GPRMC, _GPGGA]))
    first = gps.readline()
    second = gps.readline()
    assert first is not None and first.startswith("$GPRMC")
    assert second is not None and second.startswith("$GPGGA")
    assert gps.readline() is None


@pytest.mark.parametrize(
    "raw",
    [
        b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n",
        b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n",
        b"$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75\r\n",
    ],
)
def test_readline_accepts_standard_nmea_sentences(raw: bytes):
    gps = GPS(FakeUART([raw]))
    result = gps.readline()
    assert result is not None
    assert result.startswith("$")
