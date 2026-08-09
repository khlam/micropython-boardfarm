"""Local flash cache of the last real colour shown, read before Matter starts.

ESP-Matter persists the endpoint's own attributes natively, but that store
only becomes readable after `matter.Node.start()` returns (see
`firmware-packages/matter/matter/node.py`'s `_restore_endpoints`), which can
take several seconds. This module gives `main.py` a colour to show *before*
that: a small dedicated flash partition (`boot_cache`, see
`native/board/ESP32_S3_MATTER/partitions.csv`) that `main.py` writes to on
every real colour change made while commissioned, and reads back as the very
first hardware write on the next boot — so a previously-commissioned board
never flashes the boot/ready status colours, it just holds its last colour
until the real restore (or a fresh controller write) confirms or replaces it.
"""

import os

import esp32
import ujson

_PARTITION_LABEL = "boot_cache"
_MOUNT_POINT = "/boot_cache"
_CACHE_PATH = _MOUNT_POINT + "/color.json"

_mounted = [False]


def load() -> dict | None:
    """Mount the cache partition and return the last colour saved while commissioned.

    Returns:
        `{"on": bool, "color": [r, g, b]}` if a real colour was ever saved,
        otherwise `None` — treated the same as "never commissioned" by the
        caller, which falls back to the ordinary boot colour.
    """
    _mount()
    try:
        with open(_CACHE_PATH) as cache_file:
            data = ujson.load(cache_file)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or len(data.get("color", ())) != 3:
        return None
    return data


def save(*, on: bool, color: tuple) -> None:
    """Persist the last real colour rendered while commissioned.

    Args:
        on: The endpoint's on/off state at the moment of this colour.
        color: Red, green, and blue channel values in the range 0-255.
    """
    _mount()
    with open(_CACHE_PATH, "w") as cache_file:
        ujson.dump({"on": on, "color": list(color)}, cache_file)


def _mount() -> None:
    """Mount the cache partition, formatting it on first boot."""
    if _mounted[0]:
        return
    partition = esp32.Partition.find(esp32.Partition.TYPE_DATA, label=_PARTITION_LABEL)[0]
    try:
        os.mount(os.VfsLfs2(partition), _MOUNT_POINT)
    except OSError:
        os.VfsLfs2.mkfs(partition)
        os.mount(os.VfsLfs2(partition), _MOUNT_POINT)
    _mounted[0] = True
