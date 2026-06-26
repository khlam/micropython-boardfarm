"""Packed frame transition effects for clock screens."""

import random

from pixel_frame import Frame, MatrixFrame

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
_DIRECTION_MASKS = {}
_RANDOM_DISSOLVE_MASKS = {}
_DISSOLVE_SEED = 0x9E3779B1


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


def directional_mask(
    frame: object,
    total_steps: int,
    visible_steps: int,
    direction: int,
) -> bytearray:
    """Return a packed directional reveal mask."""
    visible_steps = min(total_steps, max(0, visible_steps))
    key = (frame.width, frame.height, total_steps, direction)
    cached = _DIRECTION_MASKS.get(key)
    if cached is not None:
        return cached[visible_steps]
    masks = build_direction_masks(frame.width, frame.height, total_steps, direction)
    _DIRECTION_MASKS[key] = masks
    return masks[visible_steps]


def build_direction_masks(
    width: int,
    height: int,
    total_steps: int,
    direction: int,
) -> tuple:
    """Build packed directional reveal masks for every transition step."""
    stride = (width + 7) // 8
    masks = []
    for visible_steps in range(total_steps + 1):
        data = bytearray(height * stride)
        if visible_steps > 0:
            for y in range(height):
                row_base = y * stride
                for x in range(width):
                    if direction_visible(
                        direction,
                        width,
                        height,
                        x,
                        y,
                        visible_steps,
                        total_steps,
                    ):
                        data[row_base + (x >> 3)] |= 1 << (x & 7)
        masks.append(data)
    return tuple(masks)


def mixed_mask_frame(source: object, target: object, mask: bytearray) -> object:
    """Return ``source`` and ``target`` composited through a packed mask."""
    data = bytearray(len(source.data))
    for i, item in enumerate(mask):
        data[i] = (target.data[i] & item) | (source.data[i] & (0xFF ^ item))
    return Frame.from_packed(
        source.width,
        source.height,
        source.stride,
        data,
        max(source.intensity, target.intensity),
    )


def shuffled_pixel_order(width: int, height: int, seed: int) -> list:
    """Return all pixel indices in a deterministic pseudo-random order.

    A fixed LCG-driven Fisher-Yates shuffle keeps the order stable across the
    steps of one transition (so pixels don't flicker mid-dissolve) and across
    runs (so host tests stay reproducible), while still scattering the reveal.
    """
    order = list(range(width * height))
    state = seed & 0x7FFFFFFF
    for i in range(len(order) - 1, 0, -1):
        state = ((state * 1103515245) + 12345) & 0x7FFFFFFF
        j = state % (i + 1)
        order[i], order[j] = order[j], order[i]
    return order


def build_dissolve_masks(width: int, height: int, total: int) -> tuple:
    """Build cumulative packed masks revealing pixels in random order.

    ``masks[k]`` has the first ``k / total`` of all pixels set (in the shuffled
    order), so ``masks[0]`` is empty and ``masks[total]`` is fully lit.
    """
    stride = (width + 7) // 8
    order = shuffled_pixel_order(width, height, _DISSOLVE_SEED)
    pixel_count = width * height
    data = bytearray(height * stride)
    masks = [bytes(data)]
    placed = 0
    for visible_steps in range(1, total + 1):
        target_count = visible_steps * pixel_count // total
        while placed < target_count:
            index = order[placed]
            x = index % width
            y = index // width
            data[(y * stride) + (x >> 3)] |= 1 << (x & 7)
            placed += 1
        masks.append(bytes(data))
    return tuple(masks)


def dissolve_mask(frame: object, total: int, visible_steps: int) -> bytes:
    """Return the cumulative random-dissolve mask for one frame geometry."""
    visible_steps = min(total, max(0, visible_steps))
    key = (frame.width, frame.height, total)
    cached = _RANDOM_DISSOLVE_MASKS.get(key)
    if cached is None:
        cached = build_dissolve_masks(frame.width, frame.height, total)
        _RANDOM_DISSOLVE_MASKS[key] = cached
    return cached[visible_steps]


def packed_row_bits(frame: object, y: int) -> int:
    """Return one packed row as a little-endian integer."""
    bits = 0
    row_base = y * frame.stride
    for byte_index in range(frame.stride):
        bits |= frame.data[row_base + byte_index] << (byte_index * 8)
    return bits


def write_packed_row_bits(data: bytearray, base: int, stride: int, bits: int) -> None:
    """Write a little-endian row integer into packed row bytes."""
    for byte_index in range(stride):
        data[base + byte_index] = bits & 0xFF
        bits >>= 8


def shifted_source_bits(bits: int, width: int, offset: int, dx: int) -> int:
    """Return source row bits shifted out opposite the entry direction."""
    mask = (1 << width) - 1
    if dx < 0:
        return (bits << offset) & mask
    if dx > 0:
        return bits >> offset
    return bits & mask


def shifted_target_bits(bits: int, width: int, offset: int, dx: int) -> int:
    """Return target row bits shifted in from the entry direction."""
    mask = (1 << width) - 1
    if dx < 0:
        return bits >> (width - offset)
    if dx > 0:
        return (bits << (width - offset)) & mask
    return bits & mask


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
    mask = directional_mask(source, steps, step, direction)
    return mixed_mask_frame(source, target, mask)


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
    target_y = dy * (source.height - offset_y) if dy else 0
    for y in range(source.height):
        bits = 0
        source_y = y + dy * offset_y
        if 0 <= source_y < source.height:
            bits |= shifted_source_bits(
                packed_row_bits(source, source_y),
                source.width,
                offset_x,
                dx,
            )
        target_sample_y = y - target_y
        if 0 <= target_sample_y < target.height:
            bits |= shifted_target_bits(
                packed_row_bits(target, target_sample_y),
                source.width,
                offset_x,
                dx,
            )
        write_packed_row_bits(data, y * source.stride, source.stride, bits)
    return Frame.from_packed(
        source.width,
        source.height,
        source.stride,
        data,
        max(source.intensity, target.intensity),
    )


def fade_frame(source: object, target: object, step: int, steps: int) -> object:
    """Cross-dissolve ``source`` into ``target`` by random pixel replacement."""
    return _packed_fade_frame(as_packed_frame(source), as_packed_frame(target), step, steps)


def _packed_fade_frame(source: object, target: object, step: int, steps: int) -> object:
    """Swap packed ``source`` pixels for ``target`` pixels in random order.

    Pixels toggle fully on or off as they flip between frames rather than
    dimming, so the dissolve stays visible at the display's low global brightness
    where an intensity ramp collapses to one or two MAX7219 levels. The out- and
    in-dissolves run together: one growing random mask picks the pixels already
    showing ``target`` and leaves the rest on ``source``.
    """
    if step <= 0:
        return copy_frame(source)
    if step >= steps:
        return copy_frame(target)
    return mixed_mask_frame(source, target, dissolve_mask(source, steps, step))


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
        return _packed_fade_frame(source, target, step, steps)
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
