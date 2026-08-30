"""Public interface for the supported UART radar drivers.

Every driver is a submodule subclassing `radar.stream.ReportStream` and decoding
into the one shared `Target` shape, so a caller reads any supported radar the
same way. Pick one by name with :func:`driver`, or let :func:`detect` find
whichever radar is actually wired to the UART.
"""

from radar.ld2420 import LD2420
from radar.ld2450 import LD2450
from radar.stream import DeviceNotFoundError, ReportStream, Target

__all__ = [
    "DRIVERS",
    "LD2420",
    "LD2450",
    "DeviceNotFoundError",
    "Model",
    "NoRadarError",
    "ReportStream",
    "Target",
    "detect",
    "driver",
]


class Model:
    """The supported radars. Each value is the name firmware publishes."""

    LD2450 = "ld2450"
    LD2420 = "ld2420"


# An ordered tuple rather than a dict, because MicroPython dicts are not
# insertion-ordered and detect() depends on this order: the LD2450 is probed
# first because its driver only reads, so an attached LD2450 is never written to.
DRIVERS = (
    (Model.LD2450, LD2450),
    (Model.LD2420, LD2420),
)


class NoRadarError(Exception):
    """No supported radar answered on the opened UART.

    Distinct from the ``OSError`` a failing UART raises, so a project's retry
    loop can tell "nothing is wired here" from "the bus itself is broken".
    """


def driver(model: str, *, bus_id: int, tx: int, rx: int) -> ReportStream:
    """Open the driver for one known radar model.

    Args:
        model: One of the :class:`Model` values.
        bus_id: UART number used by the microcontroller.
        tx: GPIO number connected to the radar receive pin.
        rx: GPIO number connected to the radar transmit pin.

    Returns:
        The driver, still needing ``await wait_ready()`` before it is read.

    Raises:
        ValueError: No supported radar goes by that name.
    """
    for name, driver_type in DRIVERS:
        if name == model:
            return driver_type(bus_id=bus_id, tx=tx, rx=rx)
    raise ValueError(f"unsupported radar model: {model}")


async def detect(*, bus_id: int, tx: int, rx: int) -> tuple:
    """Probe each supported radar in turn and return whichever answered.

    Every probe that stays silent is released before the next one opens, so the
    radars can share one UART and one pair of pins.

    Args:
        bus_id: UART number used by the microcontroller.
        tx: GPIO number connected to the radar receive pin.
        rx: GPIO number connected to the radar transmit pin.

    Returns:
        The detected model name and its ready driver.

    Raises:
        NoRadarError: No supported radar answered.
        OSError: The UART connection failed.
    """
    for model, driver_type in DRIVERS:
        device = driver_type(bus_id=bus_id, tx=tx, rx=rx)
        try:
            await device.wait_ready()
        except DeviceNotFoundError:
            # wait_ready() already closed this UART on its way out.
            continue
        except OSError:  # noqa: TRY203 - make the indirect UART failure contract explicit.
            raise
        return model, device
    raise NoRadarError("no supported radar answered")
