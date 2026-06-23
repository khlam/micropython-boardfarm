"""Tests for POSIX TZ footer extraction.

``posix_from_tzif_bytes`` is exercised with crafted bytes (no dependency);
``posix_for_tzid`` reads a real zone from the tzdata package, available in the
tzgen Docker stage.
"""

from __future__ import annotations

from tzgen import posix


def test_extracts_footer_from_tzif() -> None:
    data = b"TZif2" + b"\x00" * 40 + b"\nCST6CDT,M3.2.0,M11.1.0\n"
    assert posix.posix_from_tzif_bytes(data) == "CST6CDT,M3.2.0,M11.1.0"


def test_rejects_non_tzif() -> None:
    assert posix.posix_from_tzif_bytes(b"hello\nCST6\n") is None


def test_empty_footer_returns_none() -> None:
    assert posix.posix_from_tzif_bytes(b"TZif2" + b"\x00" * 8 + b"\n\n") is None


def test_posix_for_real_zone() -> None:
    assert posix.posix_for_tzid("America/Chicago", "UTC0").startswith("CST6CDT")
    # India uses the named "IST-5:30" footer rather than the numeric <+0530> form;
    # tz_offset._posix evaluates both to +5:30.
    assert posix.posix_for_tzid("Asia/Kolkata", "UTC0") == "IST-5:30"
