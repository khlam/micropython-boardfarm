# tz_offset

Convert GPS UTC date/time to local time using a fixed whole-hour UTC offset
derived from longitude (`round(lon / 15)`), since MicroPython has no timezone
database.

This is pure math (no I/O, nothing chip-specific), so the same code runs on the
MCU and under host CPython pytest, and the package has no per-chip backends.

## Public API

- `offset_hours_from_longitude(lon)` — `round(lon/15)`, clamped to `[-12, 14]`.
- `weekday(year, month, day)` — Sakamoto's algorithm, `0`=Monday … `6`=Sunday
  (matches `machine.RTC().datetime()` weekday on the rp2 port).
- `utc_to_local(year, month, day, hour, minute, second, offset_hours)` — apply the
  offset with full hour/day/month/year rollover (correct month lengths + leap years).
- `local_from_gps(date_str, utc_str, lon)` — parse `"YYYY-MM-DD"` + `"HH:MM:SSZ"`
  and return `(year, month, day, weekday, hour, minute, second)` in local time.

## Caveats

The offset is a crude nautical-style approximation: it ignores political timezone
boundaries and daylight saving. It is intended for a position-aware wall clock,
not for legal/civil time.
