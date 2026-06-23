"""Pure-Python raster grid construction, RLE encoding, and module emission.

This is the dependency-free core of tzgen: given a ``classify(lat, lon) -> index``
callable (built from timezone polygons by :mod:`tzgen.geo`) it rasterizes a global
lat/lon grid, run-length encodes it, and renders the frozen ``_tzdata.py`` module
that ships inside the ``tz_offset`` firmware package. Keeping this layer free of
shapely/numpy lets it be unit-tested quickly and deterministically.

Grid convention (must match ``tz_offset._grid`` on the MCU): row 0 is the
southernmost latitude band, col 0 the westernmost longitude band, row-major. A
cell of side ``resolution_deg`` spans ``[-90 + row*res, -90 + (row+1)*res)`` in
latitude; the rasterizer samples each cell's centre. The reserved index
``OCEAN = 0xFFFF`` marks cells no zone polygon covers.
"""

from __future__ import annotations

OCEAN = 0xFFFF
_MAX_RUN = 0xFFFF  # 2-byte run length cap in the RLE stream


def grid_dims(resolution_deg: float) -> tuple:
    """Return ``(rows, cols)`` for a global grid at ``resolution_deg`` degrees/cell."""
    return round(180 / resolution_deg), round(360 / resolution_deg)


def r_udeg(resolution_deg: float) -> int:
    """Return the cell size in micro-degrees, the integer step the MCU lookup uses."""
    return round(resolution_deg * 1_000_000)


def cell_center(row: int, col: int, rows: int, cols: int) -> tuple:
    """Return the ``(lat, lon)`` centre of grid cell ``(row, col)`` in degrees."""
    lat = -90.0 + (row + 0.5) * (180.0 / rows)
    lon = -180.0 + (col + 0.5) * (360.0 / cols)
    return lat, lon


def rasterize(rows: int, cols: int, classify: object) -> list:
    """Sample every cell centre, returning a row-major list of tz indices.

    Args:
        rows: Number of latitude bands.
        cols: Number of longitude bands.
        classify: Callable ``(lat, lon) -> int | None`` returning a zone index or
            ``None`` for cells no polygon covers.

    Returns:
        A ``rows * cols`` list of ints, with ``OCEAN`` substituted for ``None``.
    """
    grid = []
    for row in range(rows):
        for col in range(cols):
            lat, lon = cell_center(row, col, rows, cols)
            idx = classify(lat, lon)
            grid.append(OCEAN if idx is None else idx)
    return grid


def rle_encode(grid: list) -> bytes:
    """Run-length encode a grid as ``(count_hi, count_lo, val_hi, val_lo)`` quads.

    Runs longer than ``_MAX_RUN`` are split across multiple quads. Values are
    2-byte tz indices, so up to 65535 distinct zones (plus ``OCEAN``) are encodable.
    """
    out = bytearray()
    i = 0
    n = len(grid)
    while i < n:
        val = grid[i]
        j = i + 1
        while j < n and grid[j] == val and (j - i) < _MAX_RUN:
            j += 1
        count = j - i
        out += bytes((count >> 8, count & 0xFF, (val >> 8) & 0xFF, val & 0xFF))
        i = j
    return bytes(out)


def rle_decode(data: bytes) -> list:
    """Expand an RLE stream produced by :func:`rle_encode` back to a flat grid."""
    grid = []
    pos = 0
    while pos < len(data):
        count = (data[pos] << 8) | data[pos + 1]
        val = (data[pos + 2] << 8) | data[pos + 3]
        grid.extend([val] * count)
        pos += 4
    return grid


def _bytes_literal(data: bytes, per_line: int = 24) -> str:
    """Render ``data`` as wrapped, implicitly-concatenated ``b"\\xHH"`` literals.

    Adjacent string literals fold into a single flash-resident constant when frozen,
    so the grid never costs RAM at import — unlike ``bytes.fromhex`` which would
    allocate a copy. Mirrors the form of vl53l5cx's ``_config_bytes.py``.
    """
    lines = []
    for i in range(0, len(data), per_line):
        chunk = data[i : i + per_line]
        lines.append('    b"' + "".join("\\x%02x" % b for b in chunk) + '"')
    return "(\n" + "\n".join(lines) + "\n)"


def _tuple_literal(items: list, indent: str = "    ") -> str:
    """Render a list of strings as a Python tuple literal, one entry per line."""
    if not items:
        return "()"
    body = "\n".join('%s"%s",' % (indent, s) for s in items)
    return "(\n" + body + "\n)"


def emit_module(
    grid_bytes: bytes,
    posix: list,
    tzids: list,
    resolution_deg: float,
    *,
    tzbb_ref: str,
    tzdata_ref: str,
) -> str:
    """Render the full text of the generated ``tz_offset/_tzdata.py`` module.

    Args:
        grid_bytes: RLE-encoded raster from :func:`rle_encode`.
        posix: POSIX TZ strings indexed by zone index.
        tzids: IANA zone ids parallel to ``posix`` (diagnostics/tests).
        resolution_deg: Grid resolution, recorded in the header and as ``R_UDEG``.
        tzbb_ref: timezone-boundary-builder release tag, for provenance.
        tzdata_ref: IANA tzdata version, for provenance.

    Returns:
        Python source text. ``GRID`` is emitted as flash-resident ``bytes`` literals.
    """
    rows, cols = grid_dims(resolution_deg)
    header = (
        '"""Generated global timezone raster + POSIX TZ table for tz_offset.\n\n'
        "DO NOT EDIT BY HAND. Produced by ``python -m tzgen`` from\n"
        "timezone-boundary-builder %s and IANA tzdata %s at %g deg resolution.\n"
        "Regenerate via the tzgen Docker service; see\n"
        "firmware-packages/tz_offset/VENDOR.md.\n"
        '"""\n\n'
        "from micropython import const\n\n"
        "R_UDEG = const(%d)\n"
        "ROWS = const(%d)\n"
        "COLS = const(%d)\n"
        "OCEAN = const(%d)\n\n"
    ) % (tzbb_ref, tzdata_ref, resolution_deg, r_udeg(resolution_deg), rows, cols, OCEAN)
    return (
        header
        + "GRID = "
        + _bytes_literal(grid_bytes)
        + "\n\nPOSIX = "
        + _tuple_literal(posix)
        + "\n\nTZIDS = "
        + _tuple_literal(tzids)
        + "\n"
    )
