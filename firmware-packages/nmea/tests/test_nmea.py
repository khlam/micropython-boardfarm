"""Sentence decoding, malformed receiver data, and cached UTC state."""

import pytest

import nmea

_GPGGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
_GPGSA = "$GPGSA,A,3,01,02,03,04,05,06,07,08,09,10,11,12,2.0,1.0,1.8*3B"
_GPGSV = "$GPGSV,3,1,09,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75"
_GPZDA = "$GPZDA,131415,01,06,2025,00,00*49"
_GPRMC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
_EMPTY = ({}, set(), {}, {}, {}, {})


@pytest.mark.parametrize(
    "line", [_GPRMC, _GPRMC[:-2] + "6a\r\n"], ids=["uppercase", "lowercase-crlf"]
)
def test_checksum_accepts_valid_hex_and_line_endings(line):
    assert nmea.nmea_checksum_valid(line)


@pytest.mark.parametrize(
    "line",
    [_GPGGA[:-2] + "00", "$GPGGA,123519", "$GPGGA,123519*4", "$GPGGA,123519*GG"],
    ids=["mismatch", "missing", "truncated", "non_hex"],
)
def test_checksum_rejects_invalid(line):
    assert not nmea.nmea_checksum_valid(line)


@pytest.mark.parametrize(
    "line,expected",
    [
        (_GPGGA, ({}, set(), {}, {}, {"lat": 48.1173, "lon": 11.516667}, {})),
        (
            "$GNGGA,123519,3351.960,S,07036.600,W,1,08,0.9,545.4,M,46.9,M,,*5B",
            ({}, set(), {}, {}, {"lat": -33.866, "lon": -70.61}, {}),
        ),
        (
            _GPGSA,
            (
                {},
                {"01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"},
                {},
                {"pdop": 2.0, "hdop": 1.0, "vdop": 1.8},
                {},
                {},
            ),
        ),
        (
            _GPGSV,
            (
                {
                    1: {"prn": 1, "snr": 46, "sys": "GP"},
                    2: {"prn": 2, "snr": 41, "sys": "GP"},
                    12: {"prn": 12, "snr": 39, "sys": "GP"},
                    14: {"prn": 14, "snr": 45, "sys": "GP"},
                },
                set(),
                {"GP": 9},
                {},
                {},
                {},
            ),
        ),
        (_GPZDA, ({}, set(), {}, {}, {}, {"date": "2025-06-01", "utc": "13:14:15Z"})),
        (
            _GPRMC,
            (
                {},
                set(),
                {},
                {},
                {},
                {"utc": "12:35:19Z", "date": "2094-03-23", "lat": 48.1173, "lon": 11.516667},
            ),
        ),
        ("$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48", _EMPTY),
    ],
    ids=["gga_gps", "gga_multi_gnss", "gsa", "gsv", "zda", "rmc", "unsupported"],
)
def test_sentence_dispatch_returns_all_fields_in_their_slots(line, expected):
    assert nmea.parse_sentence(line) == expected


@pytest.mark.parametrize(
    "sentence,field,value",
    [
        (_GPGGA, 6, "0"),
        (_GPGGA, 2, ""),
        (_GPGGA, 4, ""),
        (_GPGGA, 2, "invalid"),
        (_GPRMC, 2, "V"),
        (_GPRMC, 1, ""),
        (_GPRMC, 1, "invalid"),
        (_GPRMC, 1, "240000"),
        (_GPRMC, 1, "126000"),
        (_GPRMC, 1, "123560"),
        (_GPRMC, 3, ""),
        (_GPRMC, 5, "invalid"),
        (_GPZDA, 1, ""),
        (_GPZDA, 1, "invalid"),
        (_GPZDA, 1, "240000"),
        (_GPZDA, 1, "136000"),
        (_GPZDA, 1, "131460"),
        (_GPZDA, 2, "00"),
        (_GPZDA, 2, "32"),
        (_GPZDA, 3, "00"),
        (_GPZDA, 3, "13"),
        (_GPZDA, 4, "invalid"),
    ],
)
def test_sentence_rejects_unusable_fix_or_time(sentence, field, value):
    parts = _parts(sentence)
    parts[field] = value
    assert nmea.parse_sentence(",".join(parts)) == _EMPTY


@pytest.mark.parametrize("tag", ["GPGGA", "GPRMC", "GPZDA", "GPGSV", "GPGSA"])
def test_truncated_sentence_has_no_usable_fields(tag):
    assert nmea.parse_sentence("$" + tag + ",123519") == _EMPTY


@pytest.mark.parametrize("date", ["", "000626", "321226", "011326", "bad", "0101"])
def test_rmc_missing_or_invalid_date_preserves_time_and_position(date):
    parts = _parts(_GPRMC)
    parts[1] = "235959.900"
    parts[4], parts[6], parts[9] = "S", "W", date
    assert nmea.parse_rmc(parts) == {
        "utc": "23:59:59Z",
        "lat": -48.1173,
        "lon": -11.516667,
    }


def test_zda_ignores_fractional_seconds_and_local_zone_fields():
    assert nmea.parse_zda(["$GNZDA", "000000.25", "1", "1", "2000", "-05", "30"]) == {
        "date": "2000-01-01",
        "utc": "00:00:00Z",
    }


@pytest.mark.parametrize("total,expected_total", [("6", {"BD": 6}), ("bad", {})])
def test_gsv_skips_bad_satellites_without_losing_remaining_signals(total, expected_total):
    parts = ["$BDGSV", "2", "1", total]
    parts += ["01", "40", "083", ""]
    parts += ["bad", "17", "308", "41"]
    parts += ["03", "07", "344", "bad"]
    parts += ["04", "22", "228", "0"]
    parts += ["05", "22", "228", "45*75"]
    parts += ["06", "22"]
    assert nmea.parse_gsv(parts) == (
        {4: {"prn": 4, "snr": 0, "sys": "BD"}, 5: {"prn": 5, "snr": 45, "sys": "BD"}},
        expected_total,
    )


@pytest.mark.parametrize("dop_fields", [[], ["bad", "1.0", "1.8"]])
def test_gsa_keeps_used_satellites_without_usable_dop(dop_fields):
    parts = ["$GNGSA", "A", "3", "01", "02"] + [""] * 10 + dop_fields
    assert nmea.parse_gsa(parts) == ({"01", "02"}, {})


@pytest.mark.parametrize(
    "new_date,cached,expected",
    [
        ("2025-06-01", None, "2025-06-01"),
        ("2026-01-01", "2025-12-31", "2026-01-01"),
        ("2025-12-31", "2026-01-01", "2026-01-01"),
    ],
    ids=["initial", "newer", "older"],
)
def test_apply_parsed_updates_time_and_retains_newest_date(new_date, cached, expected):
    assert nmea.apply_parsed({"date": new_date, "utc": "00:00:01Z"}, "23:59:59Z", cached) == (
        "00:00:01Z",
        expected,
    )


@pytest.mark.parametrize(
    "parsed,expected",
    [
        ({}, ("10:00:00Z", "2025-06-01")),
        ({"utc": "10:00:01Z"}, ("10:00:01Z", "2025-06-01")),
        ({"date": "2025-06-02"}, ("10:00:00Z", "2025-06-02")),
    ],
)
def test_apply_parsed_preserves_absent_fields(parsed, expected):
    assert nmea.apply_parsed(parsed, "10:00:00Z", "2025-06-01") == expected


@pytest.mark.parametrize(
    "utc_time,cached_date,expected",
    [
        ("13:14:15Z", "2025-06-01", "2025-06-01T13:14:15Z"),
        (None, "2025-06-01", None),
        ("13:14:15Z", None, None),
        (None, None, None),
    ],
)
def test_build_utc_full_requires_date_and_time(utc_time, cached_date, expected):
    assert nmea.build_utc_full(utc_time, cached_date) == expected


def _parts(sentence):
    return sentence.split("*", 1)[0].split(",")
