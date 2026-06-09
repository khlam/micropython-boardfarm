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


# ---------------------------------------------------------------------------
# nmea_checksum_valid
# ---------------------------------------------------------------------------


def test_checksum_valid_passes_good_sentence() -> None:
    assert nmea.nmea_checksum_valid(_GPGGA)


def test_checksum_valid_rejects_wrong_checksum() -> None:
    corrupted = _GPGGA[:-2] + "00"
    assert not nmea.nmea_checksum_valid(corrupted)


def test_checksum_valid_rejects_missing_star() -> None:
    assert not nmea.nmea_checksum_valid("$GPGGA,123519,4807.038")


def test_checksum_valid_rejects_truncated_checksum() -> None:
    assert not nmea.nmea_checksum_valid("$GPGGA,123519*4")


# ---------------------------------------------------------------------------
# parse_gga
# ---------------------------------------------------------------------------


def _gga_parts(sentence: str) -> list:
    return sentence.split("*", 1)[0].split(",")


def test_parse_gga_north_east_position() -> None:
    result = nmea.parse_gga(_gga_parts(_GPGGA))
    assert result["lat"] == pytest.approx(48.1173, abs=1e-4)
    assert result["lon"] == pytest.approx(11.5167, abs=1e-4)


def test_parse_gga_south_west_position() -> None:
    result = nmea.parse_gga(_gga_parts(_GPGGA_SOUTH_WEST))
    assert result["lat"] < 0
    assert result["lon"] < 0


def test_parse_gga_no_fix_returns_empty() -> None:
    assert nmea.parse_gga(_gga_parts(_GPGGA_NO_FIX)) == {}


def test_parse_gga_too_short_returns_empty() -> None:
    assert nmea.parse_gga(["$GPGGA", "123519"]) == {}


# ---------------------------------------------------------------------------
# parse_gsa
# ---------------------------------------------------------------------------


def _gsa_parts(sentence: str) -> list:
    return sentence.split("*", 1)[0].split(",")


def test_parse_gsa_in_use_count() -> None:
    in_use, _ = nmea.parse_gsa(_gsa_parts(_GPGSA))
    assert len(in_use) == 12


def test_parse_gsa_dop_values() -> None:
    _, dop = nmea.parse_gsa(_gsa_parts(_GPGSA))
    assert dop["pdop"] == pytest.approx(2.0)
    assert dop["hdop"] == pytest.approx(1.0)
    assert dop["vdop"] == pytest.approx(1.8)


def test_parse_gsa_empty_prn_slots_excluded() -> None:
    in_use, _ = nmea.parse_gsa(_gsa_parts(_GPGSA_SHORT))
    assert "" not in in_use
    assert len(in_use) == 2


def test_parse_gsa_short_sentence_no_dop() -> None:
    _, dop = nmea.parse_gsa(_gsa_parts(_GPGSA_SHORT))
    assert dop == {}


# ---------------------------------------------------------------------------
# parse_gsv
# ---------------------------------------------------------------------------


def _gsv_parts(sentence: str) -> list:
    return sentence.split("*", 1)[0].split(",")


def test_parse_gsv_signal_count() -> None:
    signals, _ = nmea.parse_gsv(_gsv_parts(_GPGSV))
    assert len(signals) == 4


def test_parse_gsv_signals_have_expected_keys() -> None:
    signals, _ = nmea.parse_gsv(_gsv_parts(_GPGSV))
    for sat in signals.values():
        assert "prn" in sat and "snr" in sat and "sys" in sat


def test_parse_gsv_constellation_code() -> None:
    signals, total_in_view = nmea.parse_gsv(_gsv_parts(_GPGSV))
    assert total_in_view["GP"] == 9
    assert all(s["sys"] == "GP" for s in signals.values())


def test_parse_gsv_repeated_epoch_overwrites_not_appends() -> None:
    parts = _gsv_parts(_GPGSV)
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


def _zda_parts(sentence: str) -> list:
    return sentence.split("*", 1)[0].split(",")


def test_parse_zda_returns_date_and_utc() -> None:
    result = nmea.parse_zda(_zda_parts(_GPZDA))
    assert result == {"date": "2025-06-01", "utc": "13:14:15Z"}


def test_parse_zda_invalid_hour_returns_empty() -> None:
    parts = ["$GPZDA", "250000", "01", "06", "2025", "00", "00"]
    assert nmea.parse_zda(parts) == {}


def test_parse_zda_invalid_month_returns_empty() -> None:
    parts = ["$GPZDA", "120000", "01", "13", "2025", "00", "00"]
    assert nmea.parse_zda(parts) == {}


def test_parse_zda_too_short_returns_empty() -> None:
    assert nmea.parse_zda(["$GPZDA", "131415"]) == {}


# ---------------------------------------------------------------------------
# parse_rmc
# ---------------------------------------------------------------------------


def _rmc_parts(sentence: str) -> list:
    return sentence.split("*", 1)[0].split(",")


def test_parse_rmc_valid_returns_utc() -> None:
    result = nmea.parse_rmc(_rmc_parts(_GPRMC_VALID))
    assert result["utc"] == "12:35:19Z"


def test_parse_rmc_valid_returns_position() -> None:
    result = nmea.parse_rmc(_rmc_parts(_GPRMC_VALID))
    assert result["lat"] == pytest.approx(48.1173, abs=1e-4)
    assert result["lon"] == pytest.approx(11.5167, abs=1e-4)


def test_parse_rmc_void_returns_empty() -> None:
    assert nmea.parse_rmc(_rmc_parts(_GPRMC_VOID)) == {}


def test_parse_rmc_too_short_returns_empty() -> None:
    assert nmea.parse_rmc(["$GPRMC", "123519"]) == {}


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


def test_apply_parsed_captures_new_date() -> None:
    _, cached_date = nmea.apply_parsed({"date": "2025-06-01"}, None, None)
    assert cached_date == "2025-06-01"


def test_apply_parsed_does_not_overwrite_same_date() -> None:
    _, cached_date = nmea.apply_parsed({"date": "2025-06-01"}, None, "2025-06-01")
    assert cached_date == "2025-06-01"


def test_apply_parsed_updates_to_newer_date() -> None:
    _, cached_date = nmea.apply_parsed({"date": "2025-06-02"}, None, "2025-06-01")
    assert cached_date == "2025-06-02"


def test_apply_parsed_empty_dict_changes_nothing() -> None:
    utc_time, cached_date = nmea.apply_parsed({}, "10:00:00Z", "2025-06-01")
    assert utc_time == "10:00:00Z"
    assert cached_date == "2025-06-01"


# ---------------------------------------------------------------------------
# build_utc_full
# ---------------------------------------------------------------------------


def test_build_utc_full_combines_date_and_time() -> None:
    result = nmea.build_utc_full("13:14:15Z", "2025-06-01")
    assert result == "2025-06-01T13:14:15Z"


def test_build_utc_full_returns_none_when_time_missing() -> None:
    assert nmea.build_utc_full(None, "2025-06-01") is None


def test_build_utc_full_returns_none_when_date_missing() -> None:
    assert nmea.build_utc_full("13:14:15Z", None) is None


def test_build_utc_full_returns_none_when_both_missing() -> None:
    assert nmea.build_utc_full(None, None) is None
