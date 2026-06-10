"""Host CPython tests for pure NMEA parsing logic in nmea.py.

All tests import nmea directly — no AST loading, no fake hardware.
"""

from __future__ import annotations

import nmea
import pytest

# ---------------------------------------------------------------------------
# Shared sentence fixtures
# ---------------------------------------------------------------------------

_GPGGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
_GPGGA_NO_FIX = "$GPGGA,123519,4807.038,N,01131.000,E,0,08,0.9,545.4,M,46.9,M,,*46"
_GPGGA_SOUTH_WEST = "$GPGGA,123519,3351.960,S,07036.600,W,1,08,0.9,545.4,M,46.9,M,,*45"
_GPGSA = "$GPGSA,A,3,01,02,03,04,05,06,07,08,09,10,11,12,2.0,1.0,1.8*3B"
_GPGSA_SHORT = "$GPGSA,A,3,01,02,,,,,,,,,,,*1F"
_GPGSV = "$GPGSV,3,1,09,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75"
_GPZDA = "$GPZDA,131415,01,06,2025,00,00*49"
_GPRMC_VALID = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
_GPRMC_VOID = "$GPRMC,123519,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*7D"
_GPVTG = "$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48"


def _parts(sentence: str) -> list:
    """Split a raw NMEA sentence into comma-separated fields, checksum stripped."""
    return sentence.split("*", 1)[0].split(",")


# ---------------------------------------------------------------------------
# nmea_checksum_valid
# ---------------------------------------------------------------------------


def test_checksum_valid_passes_good_sentence() -> None:
    assert nmea.nmea_checksum_valid(_GPGGA)


@pytest.mark.parametrize(
    "line",
    [
        _GPGGA[:-2] + "00",  # wrong checksum
        "$GPGGA,123519,4807.038",  # missing star
        "$GPGGA,123519*4",  # truncated checksum
    ],
    ids=["wrong_checksum", "missing_star", "truncated"],
)
def test_checksum_valid_rejects_invalid(line: str) -> None:
    assert not nmea.nmea_checksum_valid(line)


# ---------------------------------------------------------------------------
# parse_gga
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence,lat,lon",
    [
        (_GPGGA, pytest.approx(48.1173, abs=1e-4), pytest.approx(11.5167, abs=1e-4)),
        (_GPGGA_SOUTH_WEST, pytest.approx(-33.866, abs=1e-4), pytest.approx(-70.61, abs=1e-4)),
    ],
    ids=["north_east", "south_west"],
)
def test_parse_gga_position(sentence: str, lat: float, lon: float) -> None:
    result = nmea.parse_gga(_parts(sentence))
    assert result["lat"] == lat
    assert result["lon"] == lon


@pytest.mark.parametrize(
    "parts",
    [
        _parts(_GPGGA_NO_FIX),
        ["$GPGGA", "123519"],
    ],
    ids=["no_fix", "too_short"],
)
def test_parse_gga_returns_empty(parts: list) -> None:
    assert nmea.parse_gga(parts) == {}


# ---------------------------------------------------------------------------
# parse_gsa
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence,expected_count,expected_dop",
    [
        (
            _GPGSA,
            12,
            {"pdop": pytest.approx(2.0), "hdop": pytest.approx(1.0), "vdop": pytest.approx(1.8)},
        ),
        (_GPGSA_SHORT, 2, {}),
    ],
    ids=["full", "short"],
)
def test_parse_gsa(sentence: str, expected_count: int, expected_dop: dict) -> None:
    in_use, dop = nmea.parse_gsa(_parts(sentence))
    assert "" not in in_use
    assert len(in_use) == expected_count
    assert dop == expected_dop


# ---------------------------------------------------------------------------
# parse_gsv
# ---------------------------------------------------------------------------


def test_parse_gsv_full_sentence() -> None:
    signals, total_in_view = nmea.parse_gsv(_parts(_GPGSV))
    assert len(signals) == 4
    assert total_in_view["GP"] == 9
    for sat in signals.values():
        assert "prn" in sat and "snr" in sat and "sys" in sat
        assert sat["sys"] == "GP"


def test_parse_gsv_repeated_epoch_overwrites_not_appends() -> None:
    parts = _parts(_GPGSV)
    accumulated: dict = {}
    for _ in range(3):
        signals, _ = nmea.parse_gsv(parts)
        accumulated.update(signals)
    assert len(accumulated) == 4


def test_parse_gsv_short_sentence_returns_empty() -> None:
    signals, total = nmea.parse_gsv(["$GPGSV", "3"])
    assert signals == {} and total == {}


# ---------------------------------------------------------------------------
# parse_zda
# ---------------------------------------------------------------------------


def test_parse_zda_returns_date_and_utc() -> None:
    assert nmea.parse_zda(_parts(_GPZDA)) == {"date": "2025-06-01", "utc": "13:14:15Z"}


@pytest.mark.parametrize(
    "parts",
    [
        ["$GPZDA", "250000", "01", "06", "2025", "00", "00"],  # invalid hour
        ["$GPZDA", "120000", "01", "13", "2025", "00", "00"],  # invalid month
        ["$GPZDA", "131415"],  # too short
    ],
    ids=["invalid_hour", "invalid_month", "too_short"],
)
def test_parse_zda_returns_empty(parts: list) -> None:
    assert nmea.parse_zda(parts) == {}


# ---------------------------------------------------------------------------
# parse_rmc
# ---------------------------------------------------------------------------


def test_parse_rmc_valid() -> None:
    result = nmea.parse_rmc(_parts(_GPRMC_VALID))
    assert result["utc"] == "12:35:19Z"
    assert result["lat"] == pytest.approx(48.1173, abs=1e-4)
    assert result["lon"] == pytest.approx(11.5167, abs=1e-4)
    assert result["date"] == "2094-03-23"


@pytest.mark.parametrize(
    "parts",
    [
        _parts(_GPRMC_VOID),
        ["$GPRMC", "123519"],
    ],
    ids=["void", "too_short"],
)
def test_parse_rmc_returns_empty(parts: list) -> None:
    assert nmea.parse_rmc(parts) == {}


# ---------------------------------------------------------------------------
# parse_sentence dispatch
# ---------------------------------------------------------------------------


def test_parse_sentence_gga_fills_position_slot() -> None:
    _, _, _, _, position, parsed = nmea.parse_sentence(_GPGGA)
    assert position["lat"] == pytest.approx(48.1173, abs=1e-4)
    assert position["lon"] == pytest.approx(11.5167, abs=1e-4)
    assert parsed == {}


def test_parse_sentence_gsa_fills_in_use_and_dop_slots() -> None:
    _, in_use, _, dop, position, parsed = nmea.parse_sentence(_GPGSA)
    assert len(in_use) == 12
    assert dop["hdop"] == pytest.approx(1.0)
    assert position == {} and parsed == {}


def test_parse_sentence_gsv_fills_signals_slot() -> None:
    signals, _, total_in_view, dop, position, parsed = nmea.parse_sentence(_GPGSV)
    assert len(signals) == 4
    assert total_in_view["GP"] == 9
    assert dop == {} and position == {} and parsed == {}


def test_parse_sentence_zda_fills_parsed_slot() -> None:
    signals, in_use, _total, _dop, position, parsed = nmea.parse_sentence(_GPZDA)
    assert parsed == {"date": "2025-06-01", "utc": "13:14:15Z"}
    assert signals == {} and in_use == set() and position == {}


def test_parse_sentence_rmc_fills_parsed_slot() -> None:
    signals, in_use, _total, _dop, position, parsed = nmea.parse_sentence(_GPRMC_VALID)
    assert parsed["utc"] == "12:35:19Z"
    assert parsed["date"] == "2094-03-23"
    assert signals == {} and in_use == set() and position == {}


def test_parse_sentence_unknown_tag_returns_all_empty() -> None:
    signals, in_use, total_in_view, dop, position, parsed = nmea.parse_sentence(_GPVTG)
    assert signals == {}
    assert in_use == set()
    assert total_in_view == {}
    assert dop == {}
    assert position == {}
    assert parsed == {}


# ---------------------------------------------------------------------------
# apply_parsed
# ---------------------------------------------------------------------------


def test_apply_parsed_captures_utc() -> None:
    utc_time, cached_date = nmea.apply_parsed({"utc": "12:00:00Z"}, None, None)
    assert utc_time == "12:00:00Z"
    assert cached_date is None


@pytest.mark.parametrize(
    "new_date,cached,expected",
    [
        ("2025-06-01", None, "2025-06-01"),  # new date when none cached
        ("2025-06-01", "2025-06-01", "2025-06-01"),  # same date unchanged
        ("2025-06-02", "2025-06-01", "2025-06-02"),  # newer replaces older
        ("2025-06-01", "2025-06-02", "2025-06-02"),  # older does not replace newer
    ],
    ids=["from_none", "same_unchanged", "newer_replaces", "older_rejected"],
)
def test_apply_parsed_date_caching(new_date: str, cached: str | None, expected: str) -> None:
    _, result = nmea.apply_parsed({"date": new_date}, None, cached)
    assert result == expected


def test_apply_parsed_empty_dict_changes_nothing() -> None:
    utc_time, cached_date = nmea.apply_parsed({}, "10:00:00Z", "2025-06-01")
    assert utc_time == "10:00:00Z"
    assert cached_date == "2025-06-01"


# ---------------------------------------------------------------------------
# build_utc_full
# ---------------------------------------------------------------------------


def test_build_utc_full_combines_date_and_time() -> None:
    assert nmea.build_utc_full("13:14:15Z", "2025-06-01") == "2025-06-01T13:14:15Z"


@pytest.mark.parametrize(
    "utc_time,cached_date",
    [
        (None, "2025-06-01"),
        ("13:14:15Z", None),
        (None, None),
    ],
    ids=["time_missing", "date_missing", "both_missing"],
)
def test_build_utc_full_returns_none(utc_time: str | None, cached_date: str | None) -> None:
    assert nmea.build_utc_full(utc_time, cached_date) is None
