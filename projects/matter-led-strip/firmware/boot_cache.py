"""Local flash cache of the last real colour and strip length shown at boot.

ESP-Matter persists the endpoint's own attributes natively, but that store
only becomes readable after `matter.Node.start()` returns (see
`firmware-packages/matter/matter/node.py`'s `_restore_endpoints`), which can
take several seconds. This module gives `main.py` a colour to show *before*
that: a small dedicated flash partition (`boot_cache`, see
`native/board/ESP32_S3_MATTER/partitions.csv`) that `main.py` writes to on
every real colour change made while commissioned, and reads back as the very
first hardware write on the next boot — so a previously-commissioned board
never flashes the boot/ready status colours, it just holds its last colour on
the configured LED prefix until the real restore (or a fresh controller write)
confirms or replaces it.
"""

import os

import esp32
import ujson

_PARTITION_LABEL = "boot_cache"
_MOUNT_POINT = "/boot_cache"
_CACHE_PATH = _MOUNT_POINT + "/color.json"
_DEFAULT_LED_COUNT = 20
_MINIMUM_LED_COUNT = 1
_MAXIMUM_LED_COUNT = 25

_mounted = [False]


def load() -> dict | None:
    """Mount the cache partition and return the last colour saved while commissioned.

    Returns:
        `{"on": bool, "color": [r, g, b], "led_count": int}` if a real
        colour was ever saved, otherwise `None` — treated the same as "never
        commissioned" by the caller. Cache data without `led_count` uses the
        project's 20-LED default.
    """
    _mount()
    try:
        with open(_CACHE_PATH) as cache_file:
            data = ujson.load(cache_file)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or len(data.get("color", ())) != 3:
        return None
    led_count = data.get("led_count", _DEFAULT_LED_COUNT)
    if (
        not isinstance(led_count, int)
        or isinstance(led_count, bool)
        or not _MINIMUM_LED_COUNT <= led_count <= _MAXIMUM_LED_COUNT
    ):
        return None
    data["led_count"] = led_count
    return data


def save(*, on: bool, color: tuple, led_count: int) -> None:
    """Persist the last real colour rendered while commissioned.

    Args:
        on: The endpoint's on/off state at the moment of this colour.
        color: Red, green, and blue channel values in the range 0-255.
        led_count: Number of external LEDs active for this colour.
    """
    _mount()
    with open(_CACHE_PATH, "w") as cache_file:
        ujson.dump({"on": on, "color": list(color), "led_count": led_count}, cache_file)


def update_led_count(led_count: int) -> None:
    """Update the count only when a real cached colour already exists.

    A count selection must not manufacture a boot colour before the primary
    light has shown one. Matter still persists the selector independently.

    Args:
        led_count: Number of external LEDs to associate with the cached colour.
    """
    cached = load()
    if cached is None:
        return
    save(on=cached["on"], color=tuple(cached["color"]), led_count=led_count)


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
