"""GPS-to-RTC synchronization through complete and accumulated NMEA fixes."""

from __future__ import annotations

import pytest
from fake_clock import FakeRTC

import clock_sync
import tz_offset

_RMC_FIX = "$GPRMC,235958,A,3723.2475,N,12158.3416,W,0.0,0.0,230626,0.0,E*69"
_GGA_FIX = "$GPGGA,235958,3723.2475,N,12158.3416,W,1,08,0.9,545.4,M,46.9,M,,*54"
_GSV = "$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75"


def test_complete_fix_sets_local_rtc_and_latches_boot_time() -> None:
    rtc = FakeRTC()
    sync = clock_sync.ClockSynchronizer(rtc)
    assert sync.synced is False
    assert sync.boot_time is None

    sync.consume(_RMC_FIX)

    assert rtc.value == (2026, 6, 23, 1, 15, 59, 58, 0)
    assert sync.synced is True
    assert sync.boot_time == (2026, 6, 23, 1, 15, 59, 58)

    sync.consume(_sentence("GPZDA,000002,24,06,2026,00,00"))

    assert rtc.value == (2026, 6, 23, 1, 16, 0, 2, 0)
    assert sync.boot_time == (2026, 6, 23, 1, 15, 59, 58)


@pytest.mark.parametrize("initial_fix", [None, _RMC_FIX], ids=["before-sync", "after-sync"])
@pytest.mark.parametrize(
    "line",
    [None, "", _RMC_FIX[:-2] + "00", _GSV, _GGA_FIX, "$GPRMC,invalid*16"],
    ids=["no-data", "empty", "bad-checksum", "satellites", "position-only", "incomplete"],
)
def test_non_time_sentences_leave_rtc_and_sync_status_unchanged(
    initial_fix: str | None, line: str | None
) -> None:
    rtc = FakeRTC()
    sync = clock_sync.ClockSynchronizer(rtc)
    sync.consume(initial_fix)
    # Advance the RTC independently, so rewriting the previous fix is detectable.
    rtc.value = (2027, 1, 1, 4, 12, 0, 0, 0)
    before = rtc.value, sync.synced, sync.boot_time

    sync.consume(line)

    assert (rtc.value, sync.synced, sync.boot_time) == before


@pytest.mark.parametrize("position_first", [False, True])
def test_position_and_time_can_arrive_in_separate_sentences(*, position_first: bool) -> None:
    rtc = FakeRTC()
    sync = clock_sync.ClockSynchronizer(rtc)
    time_line = _sentence("GNZDA,235958,23,06,2026,00,00")
    before = rtc.value

    for line in (_GGA_FIX, time_line) if position_first else (time_line, _GGA_FIX):
        sync.consume(line)
        if line != time_line or not position_first:
            assert rtc.value == before
            assert sync.synced is False
        else:
            assert rtc.value == (2026, 6, 23, 1, 15, 59, 58, 0)
            assert sync.synced is True

    # A position-only sentence must not reset the RTC using cached, stale UTC.
    sync.consume(_sentence("GNZDA,000002,24,06,2026,00,00"))

    assert sync.synced is True
    assert rtc.value == (2026, 6, 23, 1, 16, 0, 2, 0)


@pytest.mark.parametrize(
    "longitude,hemisphere,expected_hour",
    [("12158.3416", "W", 4), ("00000.0000", "E", 12)],
    ids=["negative-offset", "zero-offset"],
)
def test_timezone_stays_at_first_fix_when_receiver_crosses_a_meridian(
    longitude: str, hemisphere: str, expected_hour: int
) -> None:
    rtc = FakeRTC()
    sync = clock_sync.ClockSynchronizer(rtc)
    sync.consume(_sentence(f"GPRMC,120000,A,3723.2475,N,{longitude},{hemisphere},0,0,230626,,"))
    boot_time = sync.boot_time

    sync.consume(_sentence("GPRMC,120001,A,5230.0000,N,01324.0000,E,0,0,230626,,"))

    assert sync.state["lon"] == pytest.approx(13.4)
    assert rtc.value == (2026, 6, 23, 1, expected_hour, 0, 1, 0)
    assert sync.boot_time == boot_time


def test_fix_lands_in_the_rtc_tuple_shape_with_a_weekday_and_no_subsecond() -> None:
    """The calendar rollovers themselves are `tz_offset`'s tests, not these.

    All this layer adds is reshaping `(y, m, d, h, mi, s)` into the RTC's
    `(y, m, d, weekday, h, mi, s, subsecond)` — so one case that crosses a year
    boundary is enough to pin the insertion point and the trailing zero.
    """
    rtc = FakeRTC()

    clock_sync.ClockSynchronizer(rtc).consume(
        _sentence("GPRMC,020030,A,3723.2475,N,12158.3416,W,0,0,010126,,")
    )

    # 2026-01-01 02:00:30 UTC at -8h is 2025-12-31 18:00:30 local, a Wednesday.
    assert rtc.value == (2025, 12, 31, 2, 18, 0, 30, 0)
    assert rtc.value[3] == tz_offset.weekday(2025, 12, 31)
    assert rtc.value[7] == 0


def test_rtc_write_failure_does_not_claim_sync_and_next_fix_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rtc = FakeRTC()
    sync = clock_sync.ClockSynchronizer(rtc)

    def _fail(_value: tuple) -> None:
        raise OSError("RTC unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(rtc, "datetime", _fail)
        with pytest.raises(OSError, match="RTC unavailable"):
            sync.consume(_RMC_FIX)

    assert sync.synced is False
    assert sync.boot_time is None
    sync.consume(_RMC_FIX)
    assert sync.synced is True
    assert sync.boot_time == (2026, 6, 23, 1, 15, 59, 58)


def _sentence(body: str) -> str:
    """Attach a checksum to a scripted receiver payload."""
    checksum = 0
    for character in body:
        checksum ^= ord(character)
    return f"${body}*{checksum:02X}"
