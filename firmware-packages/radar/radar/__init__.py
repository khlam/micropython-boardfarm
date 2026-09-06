"""Public interface for the supported UART radar drivers.

Every driver is a submodule subclassing `radar.stream.ReportStream` and decoding
into the one shared `Target` shape, so a caller reads any supported radar the
same way. Construct the one a board is wired to, or let :func:`detect` find
whichever radar is actually on the UART.
"""

from radar.ld2420 import LD2420
from radar.ld2450 import LD2450
from radar.stream import DeviceNotFoundError, ReportStream, Target

__all__ = [
    "DRIVERS",
    "LD2420",
    "LD2450",
    "DeviceNotFoundError",
    "NoRadarError",
    "ReportStream",
    "Target",
    "detect",
]

# Ordered, because detect() probes in this order: the LD2450 comes first because
# its driver only reads, so an attached LD2450 is never written to.
DRIVERS = (LD2450, LD2420)


class NoRadarError(Exception):
    """No supported radar answered on the opened UART.

    Distinct from the ``OSError`` a failing UART raises, so a project's retry
    loop can tell "nothing is wired here" from "the bus itself is broken".
    """


async def detect(*, bus_id: int, tx: int, rx: int) -> tuple:
    """Probe each supported radar in turn and return whichever answered.

    Every probe that stays silent is released before the next one opens, so the
    radars can share one UART and one pair of pins. A failing UART raises
    ``OSError`` out of the probe itself, distinguishing a broken bus from the
    silent-but-working one ``NoRadarError`` reports.

    Args:
        bus_id: UART number used by the microcontroller.
        tx: GPIO number connected to the radar receive pin.
        rx: GPIO number connected to the radar transmit pin.

    Returns:
        The detected driver's ``NAME`` and the ready driver itself.

    Raises:
        NoRadarError: No supported radar answered.
    """
    for driver_type in DRIVERS:
        device = driver_type(bus_id=bus_id, tx=tx, rx=rx)
        try:
            await device.wait_ready()
        except DeviceNotFoundError:
            # wait_ready() already closed this UART on its way out. An OSError
            # is left to propagate: the bus itself failed, so no later probe on
            # it would mean anything.
            continue
        return driver_type.NAME, device
    raise NoRadarError("no supported radar answered")
