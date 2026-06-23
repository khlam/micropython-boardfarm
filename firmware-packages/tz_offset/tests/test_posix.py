"""Host CPython tests for the pure-integer POSIX TZ parser/evaluator.

Table-driven over real POSIX TZ strings (the same form tzgen extracts from the
TZif footer). All functions are pure, so no fake hardware or grid data is needed.
"""

from __future__ import annotations

import pytest

from tz_offset import _posix

# Each case stores a POSIX string, UTC date/time fields, expected offset, and abbreviation.
_OffsetCase = tuple[str, int, int, int, int, int, int, int, str]

_OFFSET_CASES: list[_OffsetCase] = [
    # US Central — DST off in winter, on in summer.
    ("CST6CDT,M3.2.0,M11.1.0", 2026, 1, 15, 12, 0, 0, -21600, "CST"),
    ("CST6CDT,M3.2.0,M11.1.0", 2026, 7, 15, 12, 0, 0, -18000, "CDT"),
    # Spring-forward boundary: 2nd Sunday of March 2026 is the 8th, 02:00 local CST
    # = 08:00:00 UTC. One second before is still CST; at the mark it is CDT.
    ("CST6CDT,M3.2.0,M11.1.0", 2026, 3, 8, 7, 59, 59, -21600, "CST"),
    ("CST6CDT,M3.2.0,M11.1.0", 2026, 3, 8, 8, 0, 0, -18000, "CDT"),
    # Fall-back boundary: 1st Sunday of November 2026 is the 1st, 02:00 local CDT
    # = 07:00:00 UTC. One second before is still CDT; at the mark it is CST.
    ("CST6CDT,M3.2.0,M11.1.0", 2026, 11, 1, 6, 59, 59, -18000, "CDT"),
    ("CST6CDT,M3.2.0,M11.1.0", 2026, 11, 1, 7, 0, 0, -21600, "CST"),
    # US Pacific — the clock test fix lands here in June (PDT = UTC-7).
    ("PST8PDT,M3.2.0,M11.1.0", 2026, 6, 23, 23, 59, 58, -25200, "PDT"),
    ("PST8PDT,M3.2.0,M11.1.0", 2026, 1, 1, 0, 0, 0, -28800, "PST"),
    # Central Europe — last-Sunday rules with a 03:00 end time.
    ("CET-1CEST,M3.5.0,M10.5.0/3", 2026, 1, 15, 12, 0, 0, 3600, "CET"),
    ("CET-1CEST,M3.5.0,M10.5.0/3", 2026, 7, 15, 12, 0, 0, 7200, "CEST"),
    # Southern hemisphere — DST active in January, exercising the year-wrap branch.
    ("AEST-10AEDT,M10.1.0,M4.1.0/3", 2026, 1, 15, 12, 0, 0, 39600, "AEDT"),
    ("AEST-10AEDT,M10.1.0,M4.1.0/3", 2026, 7, 15, 12, 0, 0, 36000, "AEST"),
    # No-DST zones — same offset all year.
    ("UTC0", 2026, 1, 1, 0, 0, 0, 0, "UTC"),
    ("UTC0", 2026, 7, 1, 0, 0, 0, 0, "UTC"),
    ("JST-9", 2026, 3, 1, 0, 0, 0, 32400, "JST"),
    ("MST7", 2026, 7, 1, 0, 0, 0, -25200, "MST"),
    # Sub-hour offsets with bracketed numeric names.
    ("<+0530>-5:30", 2026, 6, 1, 0, 0, 0, 19800, "+0530"),
    ("<+0545>-5:45", 2026, 6, 1, 0, 0, 0, 20700, "+0545"),
    # Bracketed names + negative "/time" transition fields (Nuuk-style).
    ("<-03>3<-02>,M3.5.0/-2,M10.5.0/-1", 2026, 1, 15, 0, 0, 0, -10800, "-03"),
    ("<-03>3<-02>,M3.5.0/-2,M10.5.0/-1", 2026, 7, 15, 0, 0, 0, -7200, "-02"),
    # Julian "Jn" rules (Feb 29 never counted) — DST between day 100 and day 300.
    ("STD5DST,J100,J300", 2026, 7, 15, 12, 0, 0, -14400, "DST"),
    ("STD5DST,J100,J300", 2026, 1, 15, 12, 0, 0, -18000, "STD"),
    # Zero-based "n" rules (Feb 29 counted).
    ("STD5DST,60,300", 2026, 7, 1, 0, 0, 0, -14400, "DST"),
]


@pytest.mark.parametrize("case", _OFFSET_CASES)
def test_offset_seconds(case: _OffsetCase) -> None:
    tz, y, mo, d, h, mi, s, off, abbrev = case
    assert _posix.offset_seconds(tz, y, mo, d, h, mi, s) == (off, abbrev)


def test_parse_defaults_dst_offset_and_time() -> None:
    p = _posix.parse("CST6CDT,M3.2.0,M11.1.0")
    assert p["std_off"] == 21600
    assert p["dst_off"] == 18000  # omitted DST offset defaults to std - 1h
    assert p["has_dst"] is True
    assert p["start"] == ("M", 3, 2, 0, 7200)  # omitted /time defaults to 02:00
    assert p["end"] == ("M", 11, 1, 0, 7200)


def test_parse_no_dst() -> None:
    p = _posix.parse("MST7")
    assert p["std_off"] == 25200
    assert p["has_dst"] is False
    assert p["start"] is None
    assert p["dst_abbrev"] is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("6", 21600),
        ("-2", -7200),
        ("5:30", 19800),
        ("5:45:30", 20730),
        ("25", 90000),  # hour field above 24 is tolerated
        ("-1", -3600),
    ],
)
def test_read_offset(text: str, expected: int) -> None:
    value, end = _posix._read_offset(text, 0)
    assert value == expected
    assert end == len(text)


@pytest.mark.parametrize(
    "year,month,week,dow,expected",
    [
        (2026, 3, 2, 0, 8),  # 2nd Sunday of March 2026
        (2026, 11, 1, 0, 1),  # 1st Sunday of November 2026
        (2026, 3, 5, 0, 29),  # last Sunday of March 2026 (week 5 clamps in)
        (2026, 10, 5, 0, 25),  # last Sunday of October 2026
    ],
)
def test_mrule_dom(year: int, month: int, week: int, dow: int, expected: int) -> None:
    assert _posix._mrule_dom(year, month, week, dow) == expected


def test_read_name_bracketed_and_plain() -> None:
    assert _posix._read_name("<+0530>-5:30", 0) == ("+0530", 7)
    assert _posix._read_name("CST6CDT", 0) == ("CST", 3)
