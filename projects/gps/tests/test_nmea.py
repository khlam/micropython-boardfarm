"""Host CPython tests for pure NMEA parsing logic in nmea.py.

All tests import nmea directly — no AST loading, no fake hardware.
"""

from __future__ import annotations

import pathlib
import sys

_FIRMWARE_DIR = str(pathlib.Path(__file__).parent.parent / "firmware")
if _FIRMWARE_DIR not in sys.path:
    sys.path.insert(0, _FIRMWARE_DIR)

import nmea  # noqa: E402
import pytest  # noqa: E402

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
    """Split a raw NMEA sentence into comma-separated fields, checksum stripped.

    Args:
        sentence: The raw sentence, including its ``*`` checksum.

    Returns:
        The sentence's fields, starting with its ``$`` tag.
    """
    return sentence.split("*", 1)[0].split(",")


# ---------------------------------------------------------------------------
# nmea_checksum_valid
# ---------------------------------------------------------------------------


def test_checksum_valid_passes_good_sentence() -> None:
    """A sentence whose checksum matches its body is valid."""
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
    """A wrong, missing, or truncated checksum is invalid.

    Args:
        line: The sentence checked.
    """
    assert not nmea.nmea_checksum_valid(line)


# ---------------------------------------------------------------------------
# parse_gga
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lat", "lon"),
    [
        (_GPGGA, pytest.approx(48.1173, abs=1e-4), pytest.approx(11.5167, abs=1e-4)),
        (_GPGGA_SOUTH_WEST, pytest.approx(-33.866, abs=1e-4), pytest.approx(-70.61, abs=1e-4)),
    ],
    ids=["north_east", "south_west"],
)
def test_parse_gga_position(sentence: str, lat: float, lon: float) -> None:
    """A fixed GGA converts to decimal degrees, negative south and west.

    Args:
        sentence: The GGA sentence parsed.
        lat: Its latitude in decimal degrees.
        lon: Its longitude in decimal degrees.
    """
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
    """A GGA without a fix, or too short to hold one, yields nothing.

    Args:
        parts: The sentence's fields.
    """
    assert nmea.parse_gga(parts) == {}


# ---------------------------------------------------------------------------
# parse_gsa
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "expected_count", "expected_dop"),
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
    """A GSA yields the satellites in use, skipping blanks, and any DOP values it carries.

    Args:
        sentence: The GSA sentence parsed.
        expected_count: How many satellites are in use.
        expected_dop: The dilution-of-precision values it carries.
    """
    in_use, dop = nmea.parse_gsa(_parts(sentence))
    assert "" not in in_use
    assert len(in_use) == expected_count
    assert dop == expected_dop


# ---------------------------------------------------------------------------
# parse_gsv
# ---------------------------------------------------------------------------


def test_parse_gsv_full_sentence() -> None:
    """A GSV yields each satellite's PRN, SNR, and system, plus the count in view."""
    signals, total_in_view = nmea.parse_gsv(_parts(_GPGSV))
    assert len(signals) == 4
    assert total_in_view["GP"] == 9
    for sat in signals.values():
        assert "prn" in sat
        assert "snr" in sat
        assert "sys" in sat
        assert sat["sys"] == "GP"


def test_parse_gsv_repeated_epoch_overwrites_not_appends() -> None:
    """The same satellites reported again replace their entries rather than adding more."""
    parts = _parts(_GPGSV)
    accumulated: dict = {}
    for _ in range(3):
        signals, _ = nmea.parse_gsv(parts)
        accumulated.update(signals)
    assert len(accumulated) == 4


def test_parse_gsv_short_sentence_returns_empty() -> None:
    """A GSV too short to hold its header yields nothing."""
    signals, total = nmea.parse_gsv(["$GPGSV", "3"])
    assert signals == {}
    assert total == {}


# ---------------------------------------------------------------------------
# parse_zda
# ---------------------------------------------------------------------------


def test_parse_zda_returns_date_and_utc() -> None:
    """A ZDA yields its ISO date and UTC time."""
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
    """A ZDA with an impossible time or date, or too short, yields nothing.

    Args:
        parts: The sentence's fields.
    """
    assert nmea.parse_zda(parts) == {}


# ---------------------------------------------------------------------------
# parse_rmc
# ---------------------------------------------------------------------------


def test_parse_rmc_valid() -> None:
    """A valid RMC yields its UTC time, position, and date."""
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
    """An RMC marked void, or too short, yields nothing.

    Args:
        parts: The sentence's fields.
    """
    assert nmea.parse_rmc(parts) == {}


# ---------------------------------------------------------------------------
# parse_sentence dispatch
# ---------------------------------------------------------------------------


def test_parse_sentence_gga_fills_position_slot() -> None:
    """A GGA fills only the position slot."""
    _, _, _, _, position, parsed = nmea.parse_sentence(_GPGGA)
    assert position["lat"] == pytest.approx(48.1173, abs=1e-4)
    assert position["lon"] == pytest.approx(11.5167, abs=1e-4)
    assert parsed == {}


def test_parse_sentence_gsa_fills_in_use_and_dop_slots() -> None:
    """A GSA fills only the in-use and DOP slots."""
    _, in_use, _, dop, position, parsed = nmea.parse_sentence(_GPGSA)
    assert len(in_use) == 12
    assert dop["hdop"] == pytest.approx(1.0)
    assert position == {}
    assert parsed == {}


def test_parse_sentence_gsv_fills_signals_slot() -> None:
    """A GSV fills only the signals and in-view slots."""
    signals, _, total_in_view, dop, position, parsed = nmea.parse_sentence(_GPGSV)
    assert len(signals) == 4
    assert total_in_view["GP"] == 9
    assert dop == {}
    assert position == {}
    assert parsed == {}


def test_parse_sentence_zda_fills_parsed_slot() -> None:
    """A ZDA fills only the parsed slot."""
    signals, in_use, _total, _dop, position, parsed = nmea.parse_sentence(_GPZDA)
    assert parsed == {"date": "2025-06-01", "utc": "13:14:15Z"}
    assert signals == {}
    assert in_use == set()
    assert position == {}


def test_parse_sentence_rmc_fills_parsed_slot() -> None:
    """An RMC fills only the parsed slot."""
    signals, in_use, _total, _dop, position, parsed = nmea.parse_sentence(_GPRMC_VALID)
    assert parsed["utc"] == "12:35:19Z"
    assert parsed["date"] == "2094-03-23"
    assert signals == {}
    assert in_use == set()
    assert position == {}


def test_parse_sentence_unknown_tag_returns_all_empty() -> None:
    """A sentence type the parser doesn't handle fills no slot."""
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
    """A parsed UTC time replaces the current one and leaves the date alone."""
    utc_time, cached_date = nmea.apply_parsed({"utc": "12:00:00Z"}, None, None)
    assert utc_time == "12:00:00Z"
    assert cached_date is None


@pytest.mark.parametrize(
    ("new_date", "cached", "expected"),
    [
        ("2025-06-01", None, "2025-06-01"),  # new date when none cached
        ("2025-06-01", "2025-06-01", "2025-06-01"),  # same date unchanged
        ("2025-06-02", "2025-06-01", "2025-06-02"),  # newer replaces older
        ("2025-06-01", "2025-06-02", "2025-06-02"),  # older does not replace newer
    ],
    ids=["from_none", "same_unchanged", "newer_replaces", "older_rejected"],
)
def test_apply_parsed_date_caching(new_date: str, cached: str | None, expected: str) -> None:
    """The cached date only moves forward.

    Args:
        new_date: The date just parsed.
        cached: The date already cached, or None.
        expected: The date cached afterwards.
    """
    _, result = nmea.apply_parsed({"date": new_date}, None, cached)
    assert result == expected


def test_apply_parsed_empty_dict_changes_nothing() -> None:
    """A sentence that parsed nothing leaves the time and date unchanged."""
    utc_time, cached_date = nmea.apply_parsed({}, "10:00:00Z", "2025-06-01")
    assert utc_time == "10:00:00Z"
    assert cached_date == "2025-06-01"


# ---------------------------------------------------------------------------
# build_utc_full
# ---------------------------------------------------------------------------


def test_build_utc_full_combines_date_and_time() -> None:
    """A date and a time combine into one ISO 8601 UTC timestamp."""
    assert nmea.build_utc_full("13:14:15Z", "2025-06-01") == "2025-06-01T13:14:15Z"


@pytest.mark.parametrize(
    ("utc_time", "cached_date"),
    [
        (None, "2025-06-01"),
        ("13:14:15Z", None),
        (None, None),
    ],
    ids=["time_missing", "date_missing", "both_missing"],
)
def test_build_utc_full_returns_none(utc_time: str | None, cached_date: str | None) -> None:
    """Without both a date and a time there is no timestamp.

    Args:
        utc_time: The UTC time, or None.
        cached_date: The date, or None.
    """
    assert nmea.build_utc_full(utc_time, cached_date) is None
