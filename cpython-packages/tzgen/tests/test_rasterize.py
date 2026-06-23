"""Tests for the pure-Python raster core and the shapely-backed classifier.

Run inside the tzgen Docker stage, where shapely + tzdata are installed. The RLE
codec and module emission are exercised without any geo dependency; one test loads
the synthetic fixture through shapely to prove the full polygon -> grid path.
"""

from __future__ import annotations

import pathlib
import sys
import types

import pytest

from tzgen import geo, rasterize

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "mini.geojson"


def test_grid_dims_and_step() -> None:
    assert rasterize.grid_dims(0.25) == (720, 1440)
    assert rasterize.grid_dims(10) == (18, 36)
    assert rasterize.r_udeg(0.25) == 250000


def test_cell_center_is_band_midpoint() -> None:
    # 10-degree grid: row 12 / col 8 centre is (35, -95).
    assert rasterize.cell_center(12, 8, 18, 36) == pytest.approx((35.0, -95.0))


def test_rle_round_trips() -> None:
    grid = [5, 5, 5, 9, 9, rasterize.OCEAN, 1, 1, 1, 1]
    assert rasterize.rle_decode(rasterize.rle_encode(grid)) == grid


def test_rle_splits_runs_over_16_bits() -> None:
    grid = [7] * 70000  # exceeds the 0xFFFF per-run cap, forcing a split
    encoded = rasterize.rle_encode(grid)
    assert len(encoded) == 8  # two quads
    assert rasterize.rle_decode(encoded) == grid


def test_emit_module_is_importable() -> None:
    fake = types.ModuleType("micropython")
    fake.const = lambda x: x
    sys.modules["micropython"] = fake
    try:
        text = rasterize.emit_module(
            rasterize.rle_encode([0, 0, rasterize.OCEAN]),
            ["CST6CDT,M3.2.0,M11.1.0"],
            ["America/Chicago"],
            0.25,
            tzbb_ref="test",
            tzdata_ref="test",
        )
        namespace: dict = {}
        exec(compile(text, "_tzdata.py", "exec"), namespace)  # noqa: S102
    finally:
        del sys.modules["micropython"]
    assert namespace["ROWS"] == 720
    assert namespace["COLS"] == 1440
    assert isinstance(namespace["GRID"], bytes)
    assert namespace["POSIX"] == ("CST6CDT,M3.2.0,M11.1.0",)
    assert namespace["TZIDS"] == ("America/Chicago",)
    assert rasterize.rle_decode(namespace["GRID"]) == [0, 0, rasterize.OCEAN]


def test_classifier_assigns_fixture_zones() -> None:
    zones = geo.load_zones(str(_FIXTURE))
    index = geo.assign_indices(zones)
    classify = geo.build_classifier(zones, index)
    # Sorted ids: Chicago -> 0, New_York -> 1.
    assert index == {"America/Chicago": 0, "America/New_York": 1}
    assert classify(35.0, -95.0) == 0  # inside Chicago rectangle
    assert classify(35.0, -75.0) == 1  # inside New York rectangle
    assert classify(35.0, -85.0) is None  # gap between the rectangles
    assert classify(0.0, 0.0) is None  # open ocean


def test_rasterize_over_fixture_marks_known_cells() -> None:
    zones = geo.load_zones(str(_FIXTURE))
    index = geo.assign_indices(zones)
    classify = geo.build_classifier(zones, index)
    rows, cols = rasterize.grid_dims(10)
    grid = rasterize.rasterize(rows, cols, classify)
    assert grid[12 * cols + 8] == 0  # cell centre (35, -95) -> Chicago
    assert grid[12 * cols + 10] == 1  # cell centre (35, -75) -> New York
    assert grid[0] == rasterize.OCEAN  # far south-west cell, no coverage
