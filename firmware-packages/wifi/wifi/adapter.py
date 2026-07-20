"""Import-time selection of the chip-specific AP adapter.

Following the ``boot_status_led`` pattern, the backend is chosen once at import
based on ``os.uname().machine`` and bound to a single module-level instance. The
consuming project and the platform-neutral session never branch by chip — they
call the adapter through ``get()``. On any non-Wi-Fi machine (including host
CPython) the RP2040 no-op adapter is selected, so the package imports safely
everywhere and simply reports ``unsupported``.
"""

import os

__all__ = ["get"]

_machine = os.uname().machine
if "ESP32S3" in _machine:
    from wifi.esp32s3 import Adapter as _Adapter
elif "RP2350" in _machine:
    from wifi.rp2350 import Adapter as _Adapter
else:
    from wifi.rp2040 import Adapter as _Adapter

_adapter = _Adapter()


def get() -> object:
    """Return the singleton adapter for this chip."""
    return _adapter
