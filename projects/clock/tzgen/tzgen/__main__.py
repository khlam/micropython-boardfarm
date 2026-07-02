"""CLI entry: build ``tz_offset/_tzdata.py`` from timezone-boundary-builder + tzdata.

Downloads (or reuses a local copy of) the timezone-boundary-builder GeoJSON,
rasterizes a global lat/lon grid of zone indices, extracts each zone's POSIX TZ
footer from the IANA ``tzdata`` package, and writes the frozen module text to
stdout. Generation is a deliberate, occasional step: the Docker service redirects
stdout into the committed ``_tzdata.py`` (see VENDOR.md), keeping the firmware
build itself offline.

Run via the tzgen Docker stage, e.g.::

    docker compose run --rm tzgen > firmware-packages/tz_offset/tz_offset/_tzdata.py
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import urllib.request
import zipfile
from importlib.metadata import version
from pathlib import Path

from tzgen import geo, posix, rasterize

_RELEASE_URL = (
    "https://github.com/evansiroky/timezone-boundary-builder/releases/download/"
    "{ref}/timezones.geojson.zip"
)
_FALLBACK_POSIX = "UTC0"


def _log(message: str) -> None:
    """Write a progress line to stderr so stdout stays pure module text."""
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _tzdata_version() -> str:
    """Return the installed IANA tzdata version for the provenance header."""
    try:
        return version("tzdata")
    except Exception:  # noqa: BLE001 - provenance label only; never fail generation
        return "unknown"


def _fetch_geojson(ref: str, dest_dir: Path) -> Path:
    """Download and unzip the timezone-boundary-builder GeoJSON, returning its path."""
    url = _RELEASE_URL.format(ref=ref)
    zip_path = dest_dir / "timezones.geojson.zip"
    _log(f"downloading {url}")
    urllib.request.urlretrieve(url, zip_path)  # noqa: S310 - fixed https GitHub release
    with zipfile.ZipFile(zip_path) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".json"))
        archive.extract(name, dest_dir)
    return dest_dir / name


def _build_tables(tzid_to_index: dict) -> tuple:
    """Return ``(posix_list, tzid_list)`` ordered by zone index."""
    ordered = sorted(tzid_to_index, key=lambda t: tzid_to_index[t])
    posix_list = []
    for tzid in ordered:
        try:
            posix_list.append(posix.posix_for_tzid(tzid, _FALLBACK_POSIX))
        except Exception:  # noqa: BLE001 - missing zone falls back, never aborts
            _log(f"warning: no POSIX footer for {tzid}, using {_FALLBACK_POSIX}")
            posix_list.append(_FALLBACK_POSIX)
    return posix_list, ordered


def _parse_args(argv: list | None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(prog="tzgen", description=__doc__)
    parser.add_argument("--resolution-deg", type=float, default=0.25)
    parser.add_argument("--tzbb-ref", default="2025b")
    parser.add_argument(
        "--geojson", default=None, help="Local GeoJSON path; skips the download when set."
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    """Generate the module text and write it to stdout. Returns a process exit code."""
    args = _parse_args(argv)
    rows, cols = rasterize.grid_dims(args.resolution_deg)
    _log(f"grid {rows}x{cols} ({args.resolution_deg:g} deg)")

    with tempfile.TemporaryDirectory() as tmp:
        geojson = Path(args.geojson) if args.geojson else _fetch_geojson(args.tzbb_ref, Path(tmp))
        _log(f"loading zones from {geojson}")
        zones = geo.load_zones(str(geojson))
        tzid_to_index = geo.assign_indices(zones)
        _log(f"{len(zones)} zones, {len(tzid_to_index)} distinct ids")
        classify = geo.build_classifier(zones, tzid_to_index)
        _log(f"rasterizing {rows * cols} cells...")
        grid = rasterize.rasterize(rows, cols, classify)

    grid_bytes = rasterize.rle_encode(grid)
    _log(f"RLE: {len(grid)} cells -> {len(grid_bytes)} bytes")
    posix_list, tzid_list = _build_tables(tzid_to_index)

    module = rasterize.emit_module(
        grid_bytes,
        posix_list,
        tzid_list,
        args.resolution_deg,
        tzbb_ref=args.tzbb_ref,
        tzdata_ref=_tzdata_version(),
    )
    sys.stdout.write(module)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
