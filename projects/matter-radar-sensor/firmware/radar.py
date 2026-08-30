"""Detect and read whichever supported radar is wired to the shared UART.

Both radars use the same UART and GPIO pins, so this module probes them in turn
and presents whichever answered as one report stream. The LD2450 is probed first
because its driver only reads, so an attached LD2450 is never written to.

Reports from either radar carry the ``Target`` fields the project publishes. The
LD2420 measures range only, so its targets report ``x_mm`` and ``speed_cm_s`` as
zero; those are "not measured", not measurements.
"""

from collections import namedtuple

import ld2420
import ld2450

Target = namedtuple(
    "Target",
    ("slot", "x_mm", "y_mm", "speed_cm_s", "resolution_mm"),
)

_LD2450 = "ld2450"
_LD2420 = "ld2420"

# Probe order. Each entry names the model, its driver, and the absence error
# that means "try the next one" rather than "this UART is broken".
_DRIVERS = (
    (_LD2450, ld2450.LD2450, ld2450.DeviceNotFoundError),
    (_LD2420, ld2420.LD2420, ld2420.DeviceNotFoundError),
)


class NoRadarError(Exception):
    """No supported radar answered on the shared UART."""


class Radar:
    """Own the detected radar and normalize its reports for the project.

    UART failures from the detected driver propagate as OSError, so the retry
    loop can tell them apart from a radar that simply did not answer.
    """

    def __init__(self, *, bus_id: int, tx: int, rx: int) -> None:
        """Record the shared UART pins without opening anything.

        Args:
            bus_id: UART number used by the microcontroller.
            tx: GPIO number connected to the radar receive pin.
            rx: GPIO number connected to the radar transmit pin.
        """
        self._bus_id = bus_id
        self._tx = tx
        self._rx = rx
        self._driver = None
        self._model = None

    @property
    def model(self) -> str | None:
        """Return the detected radar model, or None before detection."""
        return self._model

    async def wait_ready(self) -> None:
        """Probe each supported radar until one answers.

        Every driver claims the same UART, so a driver that did not answer is
        closed before the next one is constructed.

        Raises:
            NoRadarError: If no supported radar answered.
        """
        for model, driver_type, absent in _DRIVERS:
            driver = driver_type(bus_id=self._bus_id, tx=self._tx, rx=self._rx)
            try:
                await driver.wait_ready()
            except absent:
                driver.close()
                continue
            self._driver = driver
            self._model = model
            return
        raise NoRadarError("no supported radar answered")

    async def read_latest(self) -> tuple | None:
        """Return the newest report as project targets, or None after a timeout.

        Returns:
            The detected targets, an empty tuple, or ``None`` after a timeout.
        """
        targets = await self._driver.read_latest()
        if targets is None or self._model == _LD2450:
            # LD2450 targets already carry every field the project publishes.
            return targets
        return tuple(
            Target(index, 0, target.distance_mm, 0, 0) for index, target in enumerate(targets, 1)
        )

    def close(self) -> None:
        """Release the detected radar, if one was detected."""
        if self._driver is not None:
            self._driver.close()
