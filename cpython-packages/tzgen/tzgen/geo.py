"""Shapely-backed timezone polygon loader and point classifier.

Isolated from the pure core (:mod:`tzgen.rasterize`) because it needs shapely +
GEOS, which only the tzgen Docker stage installs. Loads the timezone-boundary-
builder GeoJSON, assigns each distinct IANA zone id a stable integer index, and
returns a ``classify(lat, lon)`` callable backed by an STRtree so rasterizing a
global grid stays tractable.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_zones(geojson_path: str) -> list:
    """Load ``(tzid, geometry)`` pairs from a timezone-boundary-builder GeoJSON.

    Args:
        geojson_path: Path to the decompressed ``combined.json`` / ``timezones``
            FeatureCollection, whose features carry a ``tzid`` property.

    Returns:
        A list of ``(tzid, shapely_geometry)`` tuples in file order.
    """
    from shapely.geometry import shape

    data = json.loads(Path(geojson_path).read_text())
    zones = []
    for feature in data["features"]:
        tzid = feature["properties"]["tzid"]
        zones.append((tzid, shape(feature["geometry"])))
    return zones


def assign_indices(zones: list) -> dict:
    """Return a ``{tzid: index}`` map assigning sorted zone ids stable indices.

    Sorting makes regeneration deterministic, so the committed ``_tzdata.py`` and
    its ``POSIX``/``TZIDS`` ordering diff cleanly across runs.
    """
    return {tzid: i for i, tzid in enumerate(sorted({t for t, _ in zones}))}


def build_classifier(zones: list, tzid_to_index: dict) -> object:
    """Build a point-in-polygon classifier over the zone polygons.

    Args:
        zones: ``(tzid, geometry)`` pairs from :func:`load_zones`.
        tzid_to_index: Map from :func:`assign_indices`.

    Returns:
        A callable ``classify(lat, lon) -> int | None`` returning the zone index
        covering the point, or ``None`` when no polygon contains it (open water).
    """
    from shapely import STRtree
    from shapely.geometry import Point
    from shapely.prepared import prep

    geoms = [g for _, g in zones]
    indices = [tzid_to_index[t] for t, _ in zones]
    tree = STRtree(geoms)
    prepared = [prep(g) for g in geoms]

    def classify(lat: float, lon: float) -> int | None:
        point = Point(lon, lat)
        for i in tree.query(point):
            if prepared[i].contains(point):
                return indices[i]
        return None

    return classify
