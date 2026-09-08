"""Display facade that checks frame geometry and delegates hardware conversion."""

from pixel_frame import Frame


class Display:
    """Apply brightness to packed frames and write them to a display backend."""

    def __init__(
        self,
        backend: object,
        *,
        width_pixels: int,
        height_pixels: int,
        brightness: float = 1.0,
    ) -> None:
        """Bind a display backend to geometry and brightness policy.

        Args:
            backend: Object exposing ``write_frame(frame)``, ``clear()`` and
                ``flip()``.
            width_pixels: Declared visual width in pixels.
            height_pixels: Declared visual height in pixels.
            brightness: Normalized output brightness applied to frame intensity.

        Raises:
            ValueError: If geometry is not positive.
        """
        if width_pixels <= 0 or height_pixels <= 0:
            raise ValueError("display geometry must be positive")
        self._backend = backend
        self.width_pixels = width_pixels
        self.height_pixels = height_pixels
        self._brightness = _clamp(brightness)

    def flip(self) -> None:
        """Rotate the display 180 degrees."""
        self._backend.flip()

    def show(self, frame: object) -> None:
        """Render one packed frame, or the failure indicator if it cannot be shown.

        Args:
            frame: A ``pixel_frame.Frame`` matching the declared geometry.

        Raises:
            TypeError: If ``frame`` is not a ``pixel_frame.Frame``.
        """
        if not isinstance(frame, Frame):
            raise TypeError("display.show expects a pixel_frame Frame")
        if frame.width != self.width_pixels or frame.height != self.height_pixels:
            self._show_failure()
            return
        if not self._backend.write_frame(self._scale_intensity(frame)):
            self._show_failure()

    def _show_failure(self) -> None:
        """Light the four corners, falling back to a blank display."""
        frame = _corner_failure(self.width_pixels, self.height_pixels)
        if frame is None or not self._backend.write_frame(self._scale_intensity(frame)):
            self._backend.clear()

    def _scale_intensity(self, frame: Frame) -> Frame:
        """Apply the configured brightness to a packed frame's shared intensity."""
        intensity = _scale_byte(frame.intensity, self._brightness)
        if intensity == frame.intensity:
            return frame
        return Frame(frame.width, frame.height, intensity, stride=frame.stride, data=frame.data)


def _corner_failure(width: int, height: int) -> Frame | None:
    """Build a visible four-corner failure frame when geometry permits."""
    if width < 2 or height < 2:
        return None
    frame = Frame(width, height)
    for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        frame.pixel(x, y)
    return frame


def _clamp(value: float) -> float:
    """Clamp a normalized float to 0.0..1.0."""
    if value <= 0:
        return 0.0
    if value >= 1:
        return 1.0
    return value


def _scale_byte(value: int, brightness: float) -> int:
    """Scale one normalized byte by normalized brightness."""
    if value <= 0 or brightness <= 0:
        return 0
    scaled = int(value * brightness + 0.5)
    if scaled <= 0:
        return 1
    return scaled
