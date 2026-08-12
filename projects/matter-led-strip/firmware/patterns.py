"""Render controller-selected LED strip patterns without owning its hardware.

The project passes in the NeoPixel byte buffer, channel order, flush callback,
Matter endpoints, and commissioning-ownership predicate. This module owns only
animation state and ESP32 timer 1; it never claims a GPIO or imports neopixel.
"""

import time

import machine
import micropython
from color import matter_to_triple

NONE = 0
RANDOM = 1
BREATHE = 2
WAVE = 3
ALTERNATE = 4
RAINBOW = 5
CHASE = 6
TWINKLE = 7

PATTERN_LABELS = (
    "Random",
    "Breathe",
    "Wave",
    "Alternate",
    "Rainbow",
    "Chase",
    "Twinkle",
)

_TICK_MS = micropython.const(50)
_RANDOM_STEP_MS = micropython.const(500)
_BREATHE_PERIOD_MS = micropython.const(3000)
_WAVE_PERIOD_MS = micropython.const(2500)
_ALTERNATE_STEP_MS = micropython.const(600)
_RAINBOW_PERIOD_MS = micropython.const(4000)
_CHASE_STEP_MS = micropython.const(100)
_TWINKLE_STEP_MS = micropython.const(150)
_TWINKLE_DECAY = micropython.const(51)
_BYTE_MAXIMUM = micropython.const(255)
_BYTE_RANGE = micropython.const(256)
_MATTER_MAXIMUM = micropython.const(254)
_MINIMUM_PIXEL_COUNT = micropython.const(1)
_MAXIMUM_PIXEL_COUNT = micropython.const(25)

_light = [None]
_switches = [()]
_buffer = [bytearray()]
_order = [(0, 1, 2)]
_write = [None]
_available = [None]
_pixel_count = [0]
_maximum_pixel_count = [0]
_timer = [None]

_base_color = [(0, 0, 0)]
_mode = [NONE]
_started_ms = [0]
_last_step = [-1]
_random_state = [0x4D595DF4]
_twinkle_levels = [bytearray()]


def bind(
    *,
    light: object,
    switches: tuple,
    buffer: bytearray,
    order: tuple,
    write: object,
    available: object,
    pixel_count: int,
) -> None:
    """Bind endpoints and the hardware resources owned by the project.

    Args:
        light: Extended Color Light endpoint.
        switches: On/Off endpoints ordered like :data:`PATTERN_LABELS`.
        buffer: NeoPixel's preallocated channel byte buffer.
        order: Buffer offsets for red, green, and blue channels.
        write: Callable flushing the buffer to the strip.
        available: Callable reporting whether commissioning releases the strip.
        pixel_count: Initial number of active pixels in the external strip.
    """
    _light[0] = light
    _switches[0] = switches
    _buffer[0] = buffer
    _order[0] = order
    _write[0] = write
    _available[0] = available
    _pixel_count[0] = 0
    _maximum_pixel_count[0] = len(buffer) // 3
    _twinkle_levels[0] = bytearray(_maximum_pixel_count[0])
    set_pixel_count(pixel_count)


def set_pixel_count(pixel_count: int) -> None:
    """Select how many external LEDs animation frames may illuminate.

    Args:
        pixel_count: Active prefix length in the inclusive range 1-25.

    Raises:
        TypeError: The count is not a plain integer.
        ValueError: The count is outside 1-25 or exceeds the bound buffer.
    """
    if not isinstance(pixel_count, int) or isinstance(pixel_count, bool):
        raise TypeError("pixel_count must be int")
    if not _MINIMUM_PIXEL_COUNT <= pixel_count <= _MAXIMUM_PIXEL_COUNT:
        raise ValueError("pixel_count must be between 1 and 25")
    if pixel_count > _maximum_pixel_count[0]:
        raise ValueError("pixel_count exceeds the bound buffer")
    if pixel_count == _pixel_count[0]:
        return
    _pixel_count[0] = pixel_count
    _restart()


def start() -> None:
    """Start the periodic soft callback on ESP32 hardware timer 1."""
    _timer[0] = machine.Timer(1)
    _timer[0].init(
        mode=machine.Timer.PERIODIC,
        period=_TICK_MS,
        callback=_render_tick,
        hard=False,
    )


def restore() -> None:
    """Reconcile persisted virtual switches after every endpoint restores."""
    light = _light[0]
    selected = NONE
    if light.on:
        for index, pattern_switch in enumerate(_switches[0]):
            if pattern_switch.on and selected == NONE:
                selected = index + 1
    _mode[0] = selected
    _publish_selection()
    refresh(restart=True)


def select_remote(event: object) -> None:
    """Apply one controller write to a virtual pattern switch.

    Args:
        event: On/Off write event identifying the virtual endpoint.
    """
    selected = _mode_for_endpoint(event.endpoint_id)
    if selected == NONE:
        return
    if event.value:
        _mode[0] = selected
        _publish_selection()
        _restart()
    elif _mode[0] == selected:
        _mode[0] = NONE
        _restart()


def reset_color(color: tuple | None = None) -> None:
    """Select None and show a steady controller or local color.

    Args:
        color: Exact local RGB triple, or ``None`` to derive current Matter state.
    """
    _base_color[0] = matter_to_triple(_light[0]) if color is None else color
    _mode[0] = NONE
    available = _available[0]
    if available is not None and available():
        _fill(*_base_color[0])
        _flush()
        _last_step[0] = -3
    else:
        _last_step[0] = -1
    _publish_selection()
    _started_ms[0] = time.ticks_ms()


def refresh(*, restart: bool = False) -> None:
    """Apply changed power or brightness without clearing the selected mode.

    Args:
        restart: Whether an off-to-on transition restarts animation phase.
    """
    _base_color[0] = matter_to_triple(_light[0])
    if restart:
        _restart()
        return
    _last_step[0] = -1
    _render_tick(None)


def resume() -> None:
    """Restart the selected mode after commissioning releases the strip."""
    _base_color[0] = matter_to_triple(_light[0])
    _restart()


def _restart() -> None:
    """Reset phase-local state and render the first visible frame."""
    _started_ms[0] = time.ticks_ms()
    _last_step[0] = -1
    levels = _twinkle_levels[0]
    if levels is not None:
        for index in range(len(levels)):
            levels[index] = 0
    _render_tick(None)


def _render_tick(_arg: object) -> None:
    """Render one due frame from the timer's MicroPython soft callback.

    Args:
        _arg: The firing timer, or ``None`` for an immediate application render.
    """
    available = _available[0]
    if available is None or not available():
        return
    light = _light[0]
    if not light.on or light.level == 0:
        if not _begin_step(-2):
            return
        _fill(0, 0, 0)
        _flush()
        return
    mode = _mode[0]
    if mode == NONE:
        if not _begin_step(-3):
            return
        _fill(*_base_color[0])
        _flush()
        return
    elapsed_ms = time.ticks_diff(time.ticks_ms(), _started_ms[0])
    _RENDERERS[mode - 1](elapsed_ms)


def _render_random(elapsed_ms: int) -> None:
    """Render saturated random per-pixel colors at the Matter level ceiling."""
    step = elapsed_ms // _RANDOM_STEP_MS
    if not _begin_step(step):
        return
    brightness = _light[0].level
    for index in range(_pixel_count[0]):
        _wheel_pixel(index, _next_random() >> 24, brightness)
    _flush()


def _render_breathe(elapsed_ms: int) -> None:
    """Render a smooth triangular-eased selected-color pulse."""
    phase = elapsed_ms % _BREATHE_PERIOD_MS
    half_period = _BREATHE_PERIOD_MS // 2
    triangle = phase * _BYTE_MAXIMUM // half_period
    if phase >= half_period:
        triangle = (_BREATHE_PERIOD_MS - phase) * _BYTE_MAXIMUM // half_period
    factor = triangle * (510 - triangle) // _BYTE_MAXIMUM
    red, green, blue = _base_color[0]
    _fill(_scale(red, factor), _scale(green, factor), _scale(blue, factor))
    _flush()


def _render_wave(elapsed_ms: int) -> None:
    """Render one traveling selected-color brightness wave across the strip."""
    offset = elapsed_ms * _BYTE_RANGE // _WAVE_PERIOD_MS
    red, green, blue = _base_color[0]
    count = _pixel_count[0]
    for index in range(count):
        phase = (offset + index * _BYTE_RANGE // count) & _BYTE_MAXIMUM
        triangle = phase * 2 if phase < 128 else (255 - phase) * 2
        factor = triangle * (510 - triangle) // _BYTE_MAXIMUM
        _set_pixel(index, _scale(red, factor), _scale(green, factor), _scale(blue, factor))
    _flush()


def _render_alternate(elapsed_ms: int) -> None:
    """Swap adjacent selected-color and black pixels at a fixed cadence."""
    step = elapsed_ms // _ALTERNATE_STEP_MS
    if not _begin_step(step):
        return
    red, green, blue = _base_color[0]
    parity = step & 1
    for index in range(_pixel_count[0]):
        if (index & 1) == parity:
            _set_pixel(index, red, green, blue)
        else:
            _set_pixel(index, 0, 0, 0)
    _flush()


def _render_rainbow(elapsed_ms: int) -> None:
    """Render a full-strip hue wheel scrolling at the Matter level ceiling."""
    offset = elapsed_ms * _BYTE_RANGE // _RAINBOW_PERIOD_MS
    brightness = _light[0].level
    count = _pixel_count[0]
    for index in range(count):
        _wheel_pixel(index, (offset + index * _BYTE_RANGE // count) & _BYTE_MAXIMUM, brightness)
    _flush()


def _render_chase(elapsed_ms: int) -> None:
    """Advance a three-pixel selected-color head and fading trail."""
    step = elapsed_ms // _CHASE_STEP_MS
    if not _begin_step(step):
        return
    _fill(0, 0, 0)
    red, green, blue = _base_color[0]
    count = _pixel_count[0]
    for distance, factor in ((0, 255), (1, 128), (2, 64)):
        index = (step - distance) % count
        _set_pixel(index, _scale(red, factor), _scale(green, factor), _scale(blue, factor))
    _flush()


def _render_twinkle(elapsed_ms: int) -> None:
    """Add selected-color sparkles and decay each over 750 milliseconds."""
    step = elapsed_ms // _TWINKLE_STEP_MS
    if not _begin_step(step):
        return
    levels = _twinkle_levels[0]
    for index in range(_pixel_count[0]):
        levels[index] = max(0, levels[index] - _TWINKLE_DECAY)
    levels[_next_random() % _pixel_count[0]] = _BYTE_MAXIMUM
    red, green, blue = _base_color[0]
    for index in range(_pixel_count[0]):
        factor = levels[index]
        _set_pixel(index, _scale(red, factor), _scale(green, factor), _scale(blue, factor))
    _flush()


_RENDERERS = (
    _render_random,
    _render_breathe,
    _render_wave,
    _render_alternate,
    _render_rainbow,
    _render_chase,
    _render_twinkle,
)


def _begin_step(step: int) -> bool:
    """Record and accept a discrete animation step only once."""
    if step == _last_step[0]:
        return False
    _last_step[0] = step
    return True


def _mode_for_endpoint(endpoint_id: int) -> int:
    """Return the mode represented by a virtual endpoint, or None's value."""
    for index, pattern_switch in enumerate(_switches[0]):
        if pattern_switch.id == endpoint_id:
            return index + 1
    return NONE


def _publish_selection() -> None:
    """Publish the mutually exclusive virtual-switch state."""
    selected = _mode[0]
    for index, pattern_switch in enumerate(_switches[0]):
        enabled = index + 1 == selected
        if pattern_switch.on != enabled:
            pattern_switch.on = enabled


def _wheel_pixel(index: int, position: int, brightness: int) -> None:
    """Write one saturated hue-wheel color scaled to a Matter level."""
    position &= _BYTE_MAXIMUM
    if position < 85:
        red, green, blue = 255 - position * 3, position * 3, 0
    elif position < 170:
        position -= 85
        red, green, blue = 0, 255 - position * 3, position * 3
    else:
        position -= 170
        red, green, blue = position * 3, 0, 255 - position * 3
    _set_pixel(
        index,
        red * brightness // _MATTER_MAXIMUM,
        green * brightness // _MATTER_MAXIMUM,
        blue * brightness // _MATTER_MAXIMUM,
    )


def _fill(red: int, green: int, blue: int) -> None:
    """Fill the preallocated NeoPixel buffer with one RGB color."""
    for index in range(_pixel_count[0]):
        _set_pixel(index, red, green, blue)


def _set_pixel(index: int, red: int, green: int, blue: int) -> None:
    """Write RGB channels into one pixel using NeoPixel's physical order."""
    offset = index * 3
    order = _order[0]
    buffer = _buffer[0]
    buffer[offset + order[0]] = red
    buffer[offset + order[1]] = green
    buffer[offset + order[2]] = blue


def _scale(channel: int, factor: int) -> int:
    """Scale one byte channel by an inclusive byte factor."""
    return channel * factor // _BYTE_MAXIMUM


def _next_random() -> int:
    """Advance and return the allocation-free uint32 pattern PRNG."""
    value = (1664525 * _random_state[0] + 1013904223) & 0xFFFFFFFF
    _random_state[0] = value
    return value


def _flush() -> None:
    """Hold the inactive suffix black, then flush the preallocated frame."""
    for index in range(_pixel_count[0], _maximum_pixel_count[0]):
        _set_pixel(index, 0, 0, 0)
    _write[0]()  # ty: ignore[call-non-callable]
