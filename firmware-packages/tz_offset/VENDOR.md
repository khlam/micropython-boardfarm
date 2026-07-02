# tz_offset vendored data

`tz_offset/_tzdata.py` is a **generated** file: a global timezone raster plus the
per-zone POSIX TZ rule table consumed by `_grid.py` and `_posix.py`. It is not
hand-written and must not be hand-edited — CI ("Enforce vendored files unchanged")
fails if it changes without this `VENDOR.md` being touched in the same commit.

| Field | Value |
| --- | --- |
| Generator | `projects/clock/tzgen` (`python -m tzgen`) |
| Boundary source | [timezone-boundary-builder](https://github.com/evansiroky/timezone-boundary-builder) `2025b`, land-only `timezones.geojson` |
| DST rules | IANA `tzdata` `2026.2` POSIX TZ footers (RFC 8536 §3.3) |
| Resolution | 0.25° (R_UDEG 250000; 720×1440 grid) |
| Encoding | row-major RLE `(count, value)` u16 quads; `OCEAN = 0xFFFF` |

## Regenerate

```
docker compose run --rm tzgen > firmware-packages/tz_offset/tz_offset/_tzdata.py
```

Pin the inputs for reproducibility with `--tzbb-ref <tag>`; change the cell size
with `--resolution-deg <deg>`. After regenerating, update the table above and bump
`tz_offset`'s version. Regenerating is the only sanctioned way to change this file.

## Coverage and accuracy notes

- **Land only.** Open-water cells are `OCEAN`; the firmware falls back to a
  longitude-derived whole-hour offset there (`offset_hours_from_longitude`).
- **Border slop.** Cell-centre sampling at 0.25° misclassifies points within ~½
  cell (~28 km) of a zone boundary, and drops sub-cell enclaves. Acceptable for a
  wall clock.
- **Current rules.** Each POSIX string encodes the zone's *present* DST rules, so
  the clock is correct for "now"; historical/future accuracy is bounded by the
  pinned `tzdata` release.
- **Flash budget.** At 0.25° the frozen blob is ~75 KB (grid) + ~18 KB (tables).
  If firmware growth threatens the ESP32-S3 2 MiB `.bin` budget, regenerate at
  0.5° or drop `TZIDS` (the firmware needs only `GRID` + `POSIX`).
