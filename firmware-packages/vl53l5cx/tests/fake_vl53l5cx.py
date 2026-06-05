"""Host CPython test helpers for the vl53l5cx package.

Provides factory functions for building Results objects with controlled
distance and status values, used by test_vl53l5cx.py.
"""

from vl53l5cx.vl53l5cx import Results


def make_results(distance_mm: list, target_status: list) -> Results:
    """Build a Results object with the given distance and status arrays.

    Args:
        distance_mm: List of 64 integer distances in mm.
        target_status: List of 64 integer status codes.

    Returns:
        Results instance with distance_mm and target_status populated.
    """
    r = Results()
    r.distance_mm = distance_mm
    r.target_status = target_status
    return r
