# nmea

Pure NMEA-0183 sentence parsing helpers, shared across projects (gps, clock).

All functions are stateless and free of I/O, so the same code runs on the MCU
(MicroPython) and under host CPython pytest. There is no chip-specific behavior,
so this package has no per-chip backends.

## Public API

- `nmea_checksum_valid(line)` — verify the `*HH` XOR checksum.
- `parse_sentence(line)` — dispatch one raw line → `(signals, in_use, total_in_view, dop, position, parsed)`.
- `parse_rmc` / `parse_zda` / `parse_gga` / `parse_gsa` / `parse_gsv` — per-sentence parsers.
- `apply_parsed(parsed, utc_time, cached_date)` — fold time/date fields into accumulated state.
- `build_utc_full(utc_time, cached_date)` — assemble an ISO-8601 timestamp.

RMC and ZDA carry UTC time + date; RMC and GGA carry position (longitude is used
by the clock project to derive a fixed UTC offset).
