"""tzgen — build the frozen global timezone dataset for the tz_offset firmware.

Host-only tooling (CPython + shapely + tzdata, run inside the ``tzgen`` Docker
stage). It rasterizes timezone-boundary-builder polygons into a compact RLE grid
and extracts each zone's POSIX TZ rule string, emitting the committed
``firmware-packages/tz_offset/tz_offset/_tzdata.py``. Nothing here runs on the MCU.
"""

__version__ = "0.1.0"
