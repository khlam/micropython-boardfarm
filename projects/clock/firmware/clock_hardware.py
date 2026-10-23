"""Hardware construction helpers for the clock project."""

from collections import namedtuple

ClockDevices = namedtuple("ClockDevices", ("gps", "display", "rtc"))


class ClockHardware:
    """Open clock project devices from a board wiring table."""

    def __init__(
        self,
        board: object,
        display_cls: object,
        gps_cls: object,
        rtc_cls: object,
        *,
        brightness: float = 1.0,
    ) -> None:
        """Store hardware factories, the board-specific wiring, and panel brightness."""
        self._board = board
        self._display_cls = display_cls
        self._gps_cls = gps_cls
        self._rtc_cls = rtc_cls
        self._brightness = brightness
        self.display = None

    def open(self) -> object:
        """Open the display, GPS, and RTC and return them as one bundle."""
        board = self._board
        self.display = None
        display = self._display_cls(
            spi_id=board.spi_id,
            sck=board.sck,
            mosi=board.mosi,
            cs=board.cs,
            brightness=self._brightness,
        )
        gps = self._gps_cls(bus_id=board.uart_id, tx=board.tx, rx=board.rx)
        rtc = self._rtc_cls()
        self.display = display
        return ClockDevices(gps, display, rtc)

    def flip_display(self) -> None:
        """Flip the live display if one has been opened successfully."""
        if self.display is not None:
            self.display.flip()
