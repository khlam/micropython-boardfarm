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
    ) -> None:
        """Store hardware factories and the board-specific wiring."""
        self._board = board
        self._display_cls = display_cls
        self._gps_cls = gps_cls
        self._rtc_cls = rtc_cls
        self.display = None

    def open(self) -> object:
        """Open the display, GPS, and RTC and return them as one bundle."""
        self.display = None
        surface = self._board.display.surface
        display = self._display_cls(
            spi_id=self._board.display.spi_id,
            sck=self._board.display.sck,
            mosi=self._board.display.mosi,
            cs=self._board.display.cs,
            width_pixels=surface.width_pixels,
            height_pixels=surface.height_pixels,
            brightness=surface.brightness,
        )
        gps = self._gps_cls(
            bus_id=self._board.uart.bus_id,
            tx=self._board.uart.tx,
            rx=self._board.uart.rx,
        )
        rtc = self._rtc_cls()
        self.display = display
        return ClockDevices(gps, display, rtc)

    def flip_display(self) -> None:
        """Flip the live display if one has been opened successfully."""
        if self.display is not None:
            self.display.flip()
