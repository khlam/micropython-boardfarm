# tzgen

Host-only generator for the `tz_offset` firmware package's frozen timezone
dataset. It is **not** a workspace member and is absent from `uv.lock`; its
shapely/tzdata dependencies live only inside the `tzgen` Docker stage and never
reach the firmware, the pytest image, or the viz runtime.

## What it produces

`firmware-packages/tz_offset/tz_offset/_tzdata.py` — a frozen module containing:

- `GRID`: an RLE-encoded global raster (`bytes`) mapping each lat/lon cell to a
  timezone index. The reserved index `OCEAN = 0xFFFF` marks uncovered cells.
- `POSIX`: the POSIX TZ rule string per index (lifted from each zone's TZif
  footer, RFC 8536).
- `TZIDS`: the parallel IANA zone ids (diagnostics/tests).

The on-MCU lookup in `tz_offset/_grid.py` walks `GRID`; `tz_offset/_posix.py`
evaluates the matching `POSIX` string against the current UTC date.

## Regenerate

```
docker compose run --rm tzgen > firmware-packages/tz_offset/tz_offset/_tzdata.py
```

This downloads timezone-boundary-builder, rasterizes the globe, extracts POSIX
footers, and prints the module to stdout. Pin the source with
`--tzbb-ref <tag>` and the cell size with `--resolution-deg <deg>` (default
`0.25`). Because the output is a vendored blob guarded by CI, regenerating it is a
deliberate step — pair any change with a note in
`firmware-packages/tz_offset/VENDOR.md`.

## Layout

| File | Role | Deps |
| --- | --- | --- |
| `tzgen/rasterize.py` | grid build, RLE codec, module emission | pure stdlib |
| `tzgen/posix.py` | TZif-footer POSIX extraction | stdlib + `tzdata` |
| `tzgen/geo.py` | GeoJSON load + point-in-polygon classifier | `shapely` |
| `tzgen/__main__.py` | download → rasterize → emit orchestration | the above |
