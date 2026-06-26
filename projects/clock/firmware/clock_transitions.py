"""Packed frame transition effects for clock screens."""

import random

from pixel_frame import Frame, MatrixFrame

WIDTH_PIXELS = 32
HEIGHT_PIXELS = 16

TRANSITION_WIPE = 0
TRANSITION_FADE = 1
TRANSITION_SCROLL = 2
TRANSITION_INSTANT = 3
TRANSITIONS = (
    TRANSITION_WIPE,
    TRANSITION_FADE,
    TRANSITION_SCROLL,
    TRANSITION_INSTANT,
)
TRANSITION_STEPS = 20

DIRECTION_LEFT = 0
DIRECTION_RIGHT = 1
DIRECTION_TOP = 2
DIRECTION_BOTTOM = 3
DIRECTION_TOP_LEFT = 4
DIRECTION_TOP_RIGHT = 5
DIRECTION_BOTTOM_LEFT = 6
DIRECTION_BOTTOM_RIGHT = 7
DIRECTIONS = (
    DIRECTION_LEFT,
    DIRECTION_RIGHT,
    DIRECTION_TOP,
    DIRECTION_BOTTOM,
    DIRECTION_TOP_LEFT,
    DIRECTION_TOP_RIGHT,
    DIRECTION_BOTTOM_LEFT,
    DIRECTION_BOTTOM_RIGHT,
)
OPPOSITE_DIRECTIONS = (
    DIRECTION_RIGHT,
    DIRECTION_LEFT,
    DIRECTION_BOTTOM,
    DIRECTION_TOP,
    DIRECTION_BOTTOM_RIGHT,
    DIRECTION_BOTTOM_LEFT,
    DIRECTION_TOP_RIGHT,
    DIRECTION_TOP_LEFT,
)


def copy_frame(frame: object) -> object:
    """Return a byte-for-byte copy of ``frame``."""
    if isinstance(frame, Frame):
        return frame.copy()
    return MatrixFrame(frame.width, frame.height, frame.channels, bytearray(frame.data))


def frame_value(frame: object, x: int, y: int, channel: int = 0) -> int:
    """Return one frame byte, clipping out-of-bounds reads to zero."""
    if x < 0 or y < 0 or x >= frame.width or y >= frame.height:
        return 0
    if isinstance(frame, Frame):
        if channel != 0:
            return 0
        return frame.value_at(x, y)
    return frame.data[(y * frame.width + x) * frame.channels + channel]


def max_frame_value(frame: object) -> int:
    """Return the maximum byte value present in ``frame``."""
    if isinstance(frame, Frame):
        if any(frame.data):
            return frame.intensity
        return 0
    value = 0
    for item in frame.data:
        value = max(value, item)
    return value


def as_packed_frame(frame: object) -> object:
    """Return a packed monochrome view of ``frame``."""
    if isinstance(frame, Frame):
        return frame
    stride = (frame.width + 7) // 8
    data = bytearray(frame.height * stride)
    intensity = max_frame_value(frame)
    if intensity <= 0:
        return Frame.from_packed(frame.width, frame.height, stride, data, 0)
    for y in range(frame.height):
        row_base = y * stride
        for x in range(frame.width):
            for channel in range(frame.channels):
                if frame_value(frame, x, y, channel) > 0:
                    data[row_base + (x >> 3)] |= 1 << (x & 7)
                    break
    return Frame.from_packed(frame.width, frame.height, stride, data, intensity)


def blank_packed_like(frame: object, intensity: int = 0) -> object:
    """Return a blank packed frame with matching geometry."""
    return Frame.from_packed(
        frame.width,
        frame.height,
        frame.stride,
        bytearray(frame.height * frame.stride),
        intensity,
    )


def fade_step_value(max_value: int, progress: int, total: int) -> int:
    """Return one global fade intensity between off and max."""
    if max_value <= 0:
        return 0
    if progress <= 0:
        return 0
    if total <= 0 or progress >= total:
        return max_value
    return max_value * progress // total


def dither_rank(x: int, y: int, total: int) -> int:
    """Return a stable spatial rank used by masked fade frames."""
    return ((x * 5) + (y * 3)) % total


def build_dither_masks(width: int, height: int, total: int) -> tuple:
    """Build packed masks for every visible-step count."""
    stride = (width + 7) // 8
    masks = []
    for visible_steps in range(total + 1):
        data = bytearray(height * stride)
        for y in range(height):
            row_base = y * stride
            for x in range(width):
                if dither_rank(x, y, total) < visible_steps:
                    data[row_base + (x >> 3)] |= 1 << (x & 7)
        masks.append(data)
    return tuple(masks)


def direction_delta(direction: int) -> tuple:
    """Return the entry vector for ``direction``."""
    dx = 0
    dy = 0
    if direction in (DIRECTION_LEFT, DIRECTION_TOP_LEFT, DIRECTION_BOTTOM_LEFT):
        dx = -1
    elif direction in (DIRECTION_RIGHT, DIRECTION_TOP_RIGHT, DIRECTION_BOTTOM_RIGHT):
        dx = 1
    if direction in (DIRECTION_TOP, DIRECTION_TOP_LEFT, DIRECTION_TOP_RIGHT):
        dy = -1
    elif direction in (DIRECTION_BOTTOM, DIRECTION_BOTTOM_LEFT, DIRECTION_BOTTOM_RIGHT):
        dy = 1
    return dx, dy


def opposite_direction(direction: int) -> int:
    """Return the direction opposite ``direction``."""
    if direction < 0 or direction >= len(OPPOSITE_DIRECTIONS):
        return DIRECTION_TOP_LEFT
    return OPPOSITE_DIRECTIONS[direction]


def direction_rank(direction: int, width: int, height: int, x: int, y: int) -> int:
    """Return the reveal rank for one pixel from ``direction``."""
    rank = 0
    dx, dy = direction_delta(direction)
    if dx < 0:
        rank += x
    elif dx > 0:
        rank += width - 1 - x
    if dy < 0:
        rank += y
    elif dy > 0:
        rank += height - 1 - y
    return rank


def direction_total(direction: int, width: int, height: int) -> int:
    """Return the number of reveal ranks for ``direction``."""
    if direction in (DIRECTION_LEFT, DIRECTION_RIGHT):
        return width
    if direction in (DIRECTION_TOP, DIRECTION_BOTTOM):
        return height
    return width + height - 1


def direction_visible(
    direction: int,
    width: int,
    height: int,
    x: int,
    y: int,
    visible_steps: int,
    total_steps: int,
) -> bool:
    """Return whether one pixel is visible for a directional reveal."""
    if visible_steps <= 0:
        return False
    if visible_steps >= total_steps:
        return True
    total = direction_total(direction, width, height)
    visible_ranks = max(1, total * visible_steps // total_steps)
    return direction_rank(direction, width, height, x, y) < visible_ranks


def directional_dither_mask(
    frame: object,
    total: int,
    visible_steps: int,
    direction: int,
) -> bytearray:
    """Return a packed dither mask biased toward ``direction``."""
    visible_steps = min(total, max(0, visible_steps))
    data = bytearray(len(frame.data))
    if visible_steps <= 0:
        return data
    area_total = direction_total(direction, frame.width, frame.height)
    for y in range(frame.height):
        row_base = y * frame.stride
        for x in range(frame.width):
            rank = direction_rank(direction, frame.width, frame.height, x, y)
            rank = (rank * total + dither_rank(x, y, total)) // area_total
            if rank < visible_steps:
                data[row_base + (x >> 3)] |= 1 << (x & 7)
    return data


DISPLAY_DITHER_MASKS = build_dither_masks(
    WIDTH_PIXELS,
    HEIGHT_PIXELS,
    TRANSITION_STEPS // 2,
)


def dither_mask(frame: object, total: int, visible_steps: int) -> bytearray:
    """Return a packed dither mask for one frame geometry."""
    visible_steps = min(total, max(0, visible_steps))
    if (
        frame.width == WIDTH_PIXELS
        and frame.height == HEIGHT_PIXELS
        and total == TRANSITION_STEPS // 2
    ):
        return DISPLAY_DITHER_MASKS[visible_steps]
    return build_dither_masks(frame.width, frame.height, total)[visible_steps]


def masked_fade_frame(
    source: object,
    visible_steps: int,
    total_steps: int,
    step_value: int,
) -> object:
    """Render a dither-masked view of ``source`` at one fade intensity."""
    return _packed_masked_fade_frame(
        as_packed_frame(source),
        visible_steps,
        total_steps,
        step_value,
    )


def _packed_masked_fade_frame(
    source: object,
    visible_steps: int,
    total_steps: int,
    step_value: int,
    direction: int | None = None,
) -> object:
    """Render a dither-masked view of a packed ``source``."""
    if visible_steps <= 0 or step_value <= 0:
        return blank_packed_like(source)
    visible_steps = min(total_steps, visible_steps)
    value = min(step_value, max_frame_value(source))
    if value <= 0:
        return blank_packed_like(source)
    if direction is None:
        mask = dither_mask(source, total_steps, visible_steps)
    else:
        mask = directional_dither_mask(source, total_steps, visible_steps, direction)
    data = bytearray(len(source.data))
    for i, item in enumerate(source.data):
        data[i] = item & mask[i]
    return Frame.from_packed(source.width, source.height, source.stride, data, value)


def packed_bit(frame: object, x: int, y: int) -> bool:
    """Return whether one packed-frame pixel is lit."""
    if x < 0 or y < 0 or x >= frame.width or y >= frame.height:
        return False
    return bool(frame.data[y * frame.stride + (x >> 3)] & (1 << (x & 7)))


def set_packed_bit(data: bytearray, stride: int, x: int, y: int) -> None:
    """Set one packed-frame pixel."""
    data[y * stride + (x >> 3)] |= 1 << (x & 7)


def wipe_frame(
    source: object,
    target: object,
    step: int,
    steps: int,
    direction: int = DIRECTION_LEFT,
) -> object:
    """Reveal ``target`` over ``source`` from ``direction``."""
    return _packed_wipe_frame(
        as_packed_frame(source),
        as_packed_frame(target),
        step,
        steps,
        direction,
    )


def _packed_wipe_frame(
    source: object,
    target: object,
    step: int,
    steps: int,
    direction: int,
) -> object:
    """Reveal a packed ``target`` over a packed ``source`` from ``direction``."""
    if step <= 0:
        return copy_frame(source)
    if step >= steps:
        return copy_frame(target)
    data = bytearray(len(source.data))
    for y in range(source.height):
        for x in range(source.width):
            visible = direction_visible(
                direction,
                source.width,
                source.height,
                x,
                y,
                step,
                steps,
            )
            frame = target if visible else source
            if packed_bit(frame, x, y):
                set_packed_bit(data, source.stride, x, y)
    return Frame.from_packed(
        source.width,
        source.height,
        source.stride,
        data,
        max(source.intensity, target.intensity),
    )


def scroll_frame(
    source: object,
    target: object,
    step: int,
    steps: int,
    direction: int = DIRECTION_RIGHT,
) -> object:
    """Slide ``target`` in from ``direction`` while ``source`` exits opposite."""
    return _packed_scroll_frame(
        as_packed_frame(source),
        as_packed_frame(target),
        step,
        steps,
        direction,
    )


def _packed_scroll_frame(
    source: object,
    target: object,
    step: int,
    steps: int,
    direction: int,
) -> object:
    """Slide packed ``target`` in from ``direction``."""
    if step <= 0:
        return copy_frame(source)
    if step >= steps:
        return copy_frame(target)
    data = bytearray(len(source.data))
    dx, dy = direction_delta(direction)
    offset_x = source.width * step // steps if dx else 0
    offset_y = source.height * step // steps if dy else 0
    target_x = dx * (source.width - offset_x) if dx else 0
    target_y = dy * (source.height - offset_y) if dy else 0
    for y in range(source.height):
        for x in range(source.width):
            source_x = x + dx * offset_x
            source_y = y + dy * offset_y
            target_sample_x = x - target_x
            target_sample_y = y - target_y
            if packed_bit(source, source_x, source_y):
                set_packed_bit(data, source.stride, x, y)
            if packed_bit(target, target_sample_x, target_sample_y):
                set_packed_bit(data, source.stride, x, y)
    return Frame.from_packed(
        source.width,
        source.height,
        source.stride,
        data,
        max(source.intensity, target.intensity),
    )


def fade_frame(
    source: object,
    target: object,
    step: int,
    steps: int,
    direction: int = DIRECTION_LEFT,
) -> object:
    """Fade through masked low-intensity frames into ``target`` from ``direction``."""
    return _packed_fade_frame(
        as_packed_frame(source),
        as_packed_frame(target),
        step,
        steps,
        direction,
    )


def _packed_fade_frame(
    source: object,
    target: object,
    step: int,
    steps: int,
    direction: int,
) -> object:
    """Fade through masked low-intensity frames between packed endpoints."""
    if step <= 0:
        return copy_frame(source)
    if step >= steps:
        return copy_frame(target)
    half = steps // 2
    if step <= half:
        visible_steps = half - step
        value = fade_step_value(
            max_frame_value(source),
            visible_steps - 1,
            half - 1,
        )
        return _packed_masked_fade_frame(
            source,
            visible_steps,
            half,
            value,
            opposite_direction(direction),
        )
    visible_steps = step - half
    total_steps = steps - half
    value = fade_step_value(
        max_frame_value(target),
        visible_steps - 1,
        total_steps - 1,
    )
    return _packed_masked_fade_frame(target, visible_steps, total_steps, value, direction)


def frame_transition_frame(
    effect: int,
    source: object,
    target: object,
    *,
    step: int,
    steps: int,
    direction: int | None = None,
) -> object:
    """Render one transition frame between two packed frame endpoints."""
    if effect == TRANSITION_INSTANT:
        return copy_frame(target)
    if effect == TRANSITION_FADE:
        if direction is None:
            direction = DIRECTION_LEFT
        return _packed_fade_frame(source, target, step, steps, direction)
    if effect == TRANSITION_SCROLL:
        if direction is None:
            direction = DIRECTION_RIGHT
        return _packed_scroll_frame(source, target, step, steps, direction)
    if direction is None:
        direction = DIRECTION_LEFT
    return _packed_wipe_frame(source, target, step, steps, direction)


def randbelow(limit: int, rng: object | None = None) -> int:
    """Return a random integer in ``range(limit)`` using a small MCU API."""
    if rng is None:
        rng = random
    return rng.getrandbits(8) % limit


def choose_transition(rng: object | None = None) -> int:
    """Choose one transition effect."""
    return TRANSITIONS[randbelow(len(TRANSITIONS), rng)]


def choose_direction(rng: object | None = None) -> int:
    """Choose one transition entry direction."""
    return DIRECTIONS[randbelow(len(DIRECTIONS), rng)]
