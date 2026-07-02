"""Display facade that fits frames and delegates hardware conversion."""

from pixel_frame import Frame, MatrixFrame

_FAILURE_BLANK = "blank"
_FAILURE_CORNER_XS = "corner_xs"


class Display:
    """Fit normalized frames to declared display geometry and write a backend."""

    def __init__(
        self,
        backend: object,
        *,
        width_pixels: int,
        height_pixels: int,
        brightness: float = 1.0,
        allow_lossy: bool = False,
        failure_mode: str = _FAILURE_CORNER_XS,
    ) -> None:
        """Bind a display backend to geometry and brightness policy.

        Args:
            backend: Object exposing ``write_frame(frame, *, allow_lossy)`` and
                ``clear()``.
            width_pixels: Declared visual width in pixels.
            height_pixels: Declared visual height in pixels.
            brightness: Normalized output brightness applied to frame bytes.
            allow_lossy: Whether geometry downscaling and backend conversion may
                discard detail.
            failure_mode: ``"corner_xs"`` or ``"blank"``.

        Raises:
            ValueError: If geometry or failure mode is invalid.
        """
        if width_pixels <= 0 or height_pixels <= 0:
            raise ValueError("display geometry must be positive")
        if failure_mode not in (_FAILURE_CORNER_XS, _FAILURE_BLANK):
            raise ValueError("failure_mode must be 'corner_xs' or 'blank'")
        self._backend = backend
        self.width_pixels = width_pixels
        self.height_pixels = height_pixels
        self._brightness = _clamp(brightness)
        self._allow_lossy = allow_lossy
        self._failure_mode = failure_mode

    def flip(self) -> None:
        """Rotate the display 180 degrees if the backend supports it."""
        backend_flip = getattr(self._backend, "flip", None)
        if backend_flip is not None:
            backend_flip()

    def show(self, frame: object) -> None:
        """Fit, scale, and render one frame."""
        if isinstance(frame, Frame):
            if frame.width == self.width_pixels and frame.height == self.height_pixels:
                self._write_or_fail(self._scale_frame_intensity(frame))
                return
            if self._exceeds_geometry(frame):
                self._show_failure()
                return
            frame = frame.unpack()
        self._show_matrix(frame)

    def _show_matrix(self, frame: object) -> None:
        """Render a matrix frame, fitting it to geometry when needed."""
        if not isinstance(frame, MatrixFrame):
            raise TypeError("display.show expects a pixel_frame Frame or MatrixFrame")
        if frame.width == self.width_pixels and frame.height == self.height_pixels:
            self._write_or_fail(self._scale_matrix_intensity(frame))
            return
        if self._exceeds_geometry(frame):
            self._show_failure()
            return
        fitted = _fit_matrix_frame(
            frame,
            self.width_pixels,
            self.height_pixels,
            allow_downscale=self._allow_lossy,
        )
        self._write_or_fail(self._scale_matrix_intensity(fitted))

    def _exceeds_geometry(self, frame: object) -> bool:
        """Report whether a frame is larger than geometry and may not downscale."""
        return not self._allow_lossy and (
            frame.width > self.width_pixels or frame.height > self.height_pixels
        )

    def _write_or_fail(self, frame: object) -> None:
        """Write a capped frame to the backend, rendering failure if rejected."""
        if not self._backend.write_frame(frame, allow_lossy=self._allow_lossy):
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
        capped = self._scale_frame_intensity(frame)
        if not self._backend.write_frame(capped, allow_lossy=True):
            self._backend.clear()

    def _scale_matrix_intensity(self, frame: MatrixFrame) -> MatrixFrame:
        """Apply the configured brightness to normalized matrix channels."""
        if self._brightness >= 1:
            return frame
        data = bytearray(len(frame.data))
        for i, value in enumerate(frame.data):
            data[i] = _scale_byte(value, self._brightness)
        return MatrixFrame(frame.width, frame.height, frame.channels, data)

    def _scale_frame_intensity(self, frame: Frame) -> Frame:
        """Apply the configured brightness to a packed frame's shared intensity."""
        intensity = _scale_byte(frame.intensity, self._brightness)
        if intensity == frame.intensity:
            return frame
        return Frame.from_packed(frame.width, frame.height, frame.stride, frame.data, intensity)


def _fit_matrix_frame(
    frame: MatrixFrame,
    width: int,
    height: int,
    *,
    allow_downscale: bool,
) -> MatrixFrame:
    """Scale a matrix frame to fit inside target geometry and center it."""
    if frame.width > width or frame.height > height:
        if not allow_downscale:
            return MatrixFrame.blank(width, height, frame.channels)
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
    return MatrixFrame(width, height, frame.channels, data)


def _corner_failure(width: int, height: int) -> Frame | None:
    """Build a visible four-corner failure frame when geometry permits."""
    if width >= 2 and height >= 2:
        frame = Frame(width, height)
        for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
            frame.pixel(x, y)
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
