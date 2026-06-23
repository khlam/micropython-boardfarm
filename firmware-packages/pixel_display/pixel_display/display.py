"""Display facade that fits frames and delegates hardware conversion."""

from pixel_display.frame import Frame

_FAILURE_BLANK = "blank"
_FAILURE_CORNER_XS = "corner_xs"
_PHYSICAL_MIN = 0
_PHYSICAL_MAX = 255


class Display:
    """Fit normalized frames to a declared pixel surface and write a backend."""

    def __init__(
        self,
        backend: object,
        *,
        width_pixels: int,
        height_pixels: int,
        intensity_min: int = _PHYSICAL_MIN,
        intensity_max: int = _PHYSICAL_MAX,
        intensity_limit: float = 1.0,
        allow_lossy: bool = False,
        failure_mode: str = _FAILURE_CORNER_XS,
    ) -> None:
        """Bind a display backend to geometry and intensity policy.

        Args:
            backend: Object exposing ``write_frame(frame, *, allow_lossy)`` and
                ``clear()``.
            width_pixels: Declared visual width in pixels.
            height_pixels: Declared visual height in pixels.
            intensity_min: Dimmest non-zero physical intensity.
            intensity_max: Brightest physical intensity.
            intensity_limit: Normalized cap applied linearly to ``intensity_max``.
            allow_lossy: Whether geometry downscaling and backend conversion may
                discard detail.
            failure_mode: ``"corner_xs"`` or ``"blank"``.

        Raises:
            ValueError: If geometry, intensity range, or failure mode is invalid.
        """
        if width_pixels <= 0 or height_pixels <= 0:
            raise ValueError("display geometry must be positive")
        if intensity_min < 0 or intensity_max > 255 or intensity_min > intensity_max:
            raise ValueError("physical intensity bounds must be 0..255 and ordered")
        if failure_mode not in (_FAILURE_CORNER_XS, _FAILURE_BLANK):
            raise ValueError("failure_mode must be 'corner_xs' or 'blank'")
        self._backend = backend
        self.width_pixels = width_pixels
        self.height_pixels = height_pixels
        self._intensity_min = intensity_min
        self._intensity_max = intensity_max
        self._intensity_limit = _clamp(intensity_limit)
        self._allow_lossy = allow_lossy
        self._failure_mode = failure_mode

    def show(self, frame: Frame) -> None:
        """Fit, scale, and render one frame."""
        if not self._allow_lossy and (
            frame.width > self.width_pixels or frame.height > self.height_pixels
        ):
            self._show_failure()
            return
        fitted = _fit_frame(
            frame,
            self.width_pixels,
            self.height_pixels,
            allow_downscale=self._allow_lossy,
        )
        physical = self._scale_intensity(fitted)
        if not self._backend.write_frame(physical, allow_lossy=self._allow_lossy):
            self._show_failure()

    def _show_failure(self) -> None:
        """Render the configured failure indicator."""
        if self._failure_mode == _FAILURE_BLANK:
            self._backend.clear()
            return
        frame = _corner_failure(self.width_pixels, self.height_pixels)
        if frame is None:
            self._backend.clear()
            return
        physical = self._scale_intensity(frame)
        if not self._backend.write_frame(physical, allow_lossy=True):
            self._backend.clear()

    def _scale_intensity(self, frame: Frame) -> Frame:
        """Map normalized byte channels into the configured physical range."""
        data = bytearray(len(frame.data))
        capped_max = self._intensity_min + int(
            (self._intensity_max - self._intensity_min) * self._intensity_limit + 0.5
        )
        for i, value in enumerate(frame.data):
            if value <= 0:
                data[i] = 0
            else:
                data[i] = self._intensity_min + int(
                    (capped_max - self._intensity_min) * value / 255 + 0.5
                )
        return Frame(frame.width, frame.height, frame.channels, data)


def _fit_frame(frame: Frame, width: int, height: int, *, allow_downscale: bool) -> Frame:
    """Scale a frame to fit inside target geometry and center it."""
    if frame.width > width or frame.height > height:
        if not allow_downscale:
            return Frame.blank(width, height, frame.channels)
        out_width, out_height = _downscaled_size(frame.width, frame.height, width, height)
    else:
        scale = min(width // frame.width, height // frame.height)
        scale = max(scale, 1)
        out_width = frame.width * scale
        out_height = frame.height * scale
    x0 = (width - out_width) // 2
    y0 = (height - out_height) // 2
    data = bytearray(width * height * frame.channels)
    for y in range(out_height):
        src_y = y * frame.height // out_height
        for x in range(out_width):
            src_x = x * frame.width // out_width
            src = (src_y * frame.width + src_x) * frame.channels
            dst = ((y0 + y) * width + x0 + x) * frame.channels
            data[dst : dst + frame.channels] = frame.data[src : src + frame.channels]
    return Frame(width, height, frame.channels, data)


def _corner_failure(width: int, height: int) -> Frame | None:
    """Build a visible four-corner failure frame when geometry permits."""
    if width >= 5 and height >= 7:
        frame = Frame.blank(width, height)
        glyph = Frame.text("x")
        _blit(glyph, frame, 0, 0)
        _blit(glyph, frame, width - glyph.width, 0)
        _blit(glyph, frame, 0, height - glyph.height)
        _blit(glyph, frame, width - glyph.width, height - glyph.height)
        return frame
    if width >= 2 and height >= 2:
        frame = Frame.blank(width, height)
        for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
            frame.data[y * width + x] = 255
        return frame
    return None


def _downscaled_size(src_width: int, src_height: int, dst_width: int, dst_height: int) -> tuple:
    """Return the largest aspect-preserving size within the destination."""
    if src_width * dst_height > src_height * dst_width:
        out_width = dst_width
        out_height = max(1, src_height * dst_width // src_width)
    else:
        out_height = dst_height
        out_width = max(1, src_width * dst_height // src_height)
    return out_width, out_height


def _blit(src: Frame, dst: Frame, x0: int, y0: int) -> None:
    """Copy one one-channel frame into another without clipping."""
    for y in range(src.height):
        for x in range(src.width):
            dst.data[(y0 + y) * dst.width + x0 + x] = src.data[y * src.width + x]


def _clamp(value: float) -> float:
    """Clamp a normalized float to 0.0..1.0."""
    if value <= 0:
        return 0.0
    if value >= 1:
        return 1.0
    return value
