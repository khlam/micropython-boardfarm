"""Host CPython tests for GPS parsing and RTC synchronization.

A fix only counts once date, time, and longitude have all arrived — they come
from different NMEA sentences, so the synchronizer accumulates them and sets the
RTC on the first complete set.
"""

from __future__ import annotations

import pytest
from fake_clock import FakeRTC

import clock_sync

# 23 Jun 2026, 23:59:58 UTC at 121.97W -> longitude offset -8h -> 15:59:58 local.
_RMC_FIX = "$GPRMC,235958,A,3723.2475,N,12158.3416,W,0.0,0.0,230626,0.0,E*69"
_GGA_FIX = "$GPGGA,235958,3723.2475,N,12158.3416,W,1,08,0.9,545.4,M,46.9,M,,*54"
_GSV = "$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75"


def test_a_complete_rmc_fix_sets_the_rtc_to_local_time() -> None:
    rtc = FakeRTC()

    clock_sync.sync_from_line(_RMC_FIX, rtc, {})

    assert rtc.value == (2026, 6, 23, 1, 15, 59, 58, 0)


def test_a_complete_fix_marks_the_state_synced() -> None:
    state: dict = {}

    clock_sync.sync_from_line(_RMC_FIX, FakeRTC(), state)

    assert state["synced"] is True


def test_a_line_with_a_bad_checksum_is_ignored() -> None:
    rtc = FakeRTC()
    before = rtc.value

    clock_sync.sync_from_line(_RMC_FIX[:-2] + "00", rtc, {})

    assert rtc.value == before


def test_a_missing_line_is_ignored() -> None:
    rtc = FakeRTC()
    before = rtc.value

    clock_sync.sync_from_line(None, rtc, {})

    assert rtc.value == before


def test_a_sentence_without_position_does_not_sync() -> None:
    """GSV carries satellites but no fix, so it must not move the clock."""
    rtc = FakeRTC()
    before = rtc.value
    state: dict = {}

    clock_sync.sync_from_line(_GSV, rtc, state)

    assert rtc.value == before
    assert state.get("synced") is not True


def test_gga_contributes_position_but_cannot_complete_a_fix_alone() -> None:
    """GGA carries position and no date, so it feeds the offset but never syncs.

    Only sentences that supply a UTC timestamp (RMC, ZDA) can set the clock; GGA
    is the position source a multi-GNSS receiver reports most often.
    """
    rtc = FakeRTC()
    before = rtc.value
    state: dict = {}

    clock_sync.sync_from_line(_GGA_FIX, rtc, state)

    assert state["lon"] == pytest.approx(-121.97, abs=0.01)
    assert state.get("synced") is not True
    assert rtc.value == before


def test_the_timezone_offset_is_latched_on_the_first_fix() -> None:
    """Crossing a meridian must not jump the displayed time mid-run."""
    state: dict = {}

    clock_sync.sync_from_line(_RMC_FIX, FakeRTC(), state)
    first_offset = state["offset_s"]
    state["lon"] = 13.4  # teleport to Berlin
    clock_sync.sync_from_line(_RMC_FIX, FakeRTC(), state)

    assert state["offset_s"] == first_offset == -8 * 3_600


def test_gps_offset_derives_whole_hours_from_longitude() -> None:
    assert clock_sync.gps_offset({"lon": 13.4}) == 3_600
    assert clock_sync.gps_offset({"lon": -121.97}) == -8 * 3_600


@pytest.mark.parametrize(
    "date_str,utc_str,expected",
    [
        ("2026-06-23", "23:59:58Z", (2026, 6, 23, 23, 59, 58)),
        ("2026-01-01", "00:00:00Z", (2026, 1, 1, 0, 0, 0)),
    ],
)
def test_parse_utc_parts_splits_the_gps_strings(
    date_str: str, utc_str: str, expected: tuple
) -> None:
    assert clock_sync.parse_utc_parts(date_str, utc_str) == expected


def test_local_from_offset_rolls_the_date_backwards() -> None:
    """A negative offset near midnight must borrow a day, not clamp."""
    local = clock_sync.local_from_offset("2026-06-23", "02:00:30Z", -7 * 3_600)

    assert local == (2026, 6, 22, 0, 19, 0, 30)


def test_rtc_datetime_appends_the_subsecond_field() -> None:
    local = (2026, 6, 23, 1, 15, 59, 58)

    assert clock_sync.rtc_datetime(local) == (2026, 6, 23, 1, 15, 59, 58, 0)


def test_synchronizer_exposes_synced_after_a_complete_fix() -> None:
    sync = clock_sync.ClockSynchronizer(FakeRTC())
    assert sync.synced is False

    sync.consume(_RMC_FIX)

    assert sync.synced is True


def test_synchronizer_latches_boot_time_on_the_first_fix_only() -> None:
    """The uptime screen needs a fixed reference instant, not a moving one."""
    rtc = FakeRTC()
    sync = clock_sync.ClockSynchronizer(rtc)

    sync.consume(_RMC_FIX)
    first_boot = sync.boot_time
    rtc.value = (2027, 1, 1, 4, 0, 0, 0, 0)
    sync.consume(_RMC_FIX)

    assert first_boot == (2026, 6, 23, 1, 15, 59, 58)
    assert sync.boot_time == first_boot


def test_synchronizer_leaves_boot_time_unset_until_a_fix_arrives() -> None:
    sync = clock_sync.ClockSynchronizer(FakeRTC())

    sync.consume(_GSV)

    assert sync.boot_time is None
    assert sync.synced is False
