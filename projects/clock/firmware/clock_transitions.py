"""Packed frame transition effects for clock screens."""

import random

from pixel_display import Frame, PackedFrame

from clock_text import HEIGHT_PIXELS, WIDTH_PIXELS

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


def copy_frame(frame: object) -> object:
    """Return a byte-for-byte copy of ``frame``."""
    if isinstance(frame, PackedFrame):
        return frame.copy()
    return Frame(frame.width, frame.height, frame.channels, bytearray(frame.data))


def frame_value(frame: object, x: int, y: int, channel: int = 0) -> int:
    """Return one frame byte, clipping out-of-bounds reads to zero."""
    if x < 0 or y < 0 or x >= frame.width or y >= frame.height:
        return 0
    if isinstance(frame, PackedFrame):
        if channel != 0:
            return 0
        return frame.value_at(x, y)
    return frame.data[(y * frame.width + x) * frame.channels + channel]


def max_frame_value(frame: object) -> int:
    """Return the maximum byte value present in ``frame``."""
    if isinstance(frame, PackedFrame):
        if any(frame.data):
            return frame.intensity
        return 0
    value = 0
    for item in frame.data:
        value = max(value, item)
    return value


def as_packed_frame(frame: object) -> object:
    """Return a packed monochrome view of ``frame``."""
    if isinstance(frame, PackedFrame):
        return frame
    stride = (frame.width + 7) // 8
    data = bytearray(frame.height * stride)
    intensity = max_frame_value(frame)
    if intensity <= 0:
        return PackedFrame(frame.width, frame.height, stride, data, 0)
    for y in range(frame.height):
        row_base = y * stride
        for x in range(frame.width):
            for channel in range(frame.channels):
                if frame_value(frame, x, y, channel) > 0:
                    data[row_base + (x >> 3)] |= 1 << (x & 7)
                    break
    return PackedFrame(frame.width, frame.height, stride, data, intensity)


def blank_packed_like(frame: object, intensity: int = 0) -> object:
    """Return a blank packed frame with matching geometry."""
    return PackedFrame(
        frame.width,
        frame.height,
        frame.stride,
        bytearray(frame.height * frame.stride),
        intensity,
    )


def min_visible_source_byte(intensity_limit: float) -> int:
    """Return the lowest source byte expected to survive display capping."""
    if intensity_limit <= 0:
        return 255
    capped_max = int(255 * intensity_limit + 0.5)
    if capped_max <= 0:
        return 255
    value = (255 + (2 * capped_max) - 1) // (2 * capped_max)
    if value < 1:
        return 1
    if value > 255:
        return 255
    return value


def transition_pixel_value(source_value: int, step_value: int, min_visible: int) -> int:
    """Scale one lit transition pixel without dropping below visible range."""
    if source_value <= 0:
        return 0
    if source_value <= min_visible:
        return source_value
    step_value = max(step_value, min_visible)
    if step_value > source_value:
        return source_value
    return step_value


def fade_step_value(max_value: int, progress: int, total: int, min_visible: int) -> int:
    """Return one global fade intensity between visible minimum and max."""
    if max_value <= 0:
        return 0
    if max_value <= min_visible:
        return max_value
    if progress <= 0:
        return min_visible
    if total <= 0 or progress >= total:
        return max_value
    return min_visible + ((max_value - min_visible) * progress // total)


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
    min_visible: int,
) -> object:
    """Render a dither-masked view of ``source`` at one fade intensity."""
    source = as_packed_frame(source)
    if visible_steps <= 0 or step_value <= 0:
        return blank_packed_like(source)
    visible_steps = min(total_steps, visible_steps)
    value = transition_pixel_value(max_frame_value(source), step_value, min_visible)
    if value <= 0:
        return blank_packed_like(source)
    mask = dither_mask(source, total_steps, visible_steps)
    data = bytearray(len(source.data))
    for i, item in enumerate(source.data):
        data[i] = item & mask[i]
    return PackedFrame(source.width, source.height, source.stride, data, value)


def wipe_frame(source: object, target: object, step: int, steps: int) -> object:
    """Reveal ``target`` left-to-right over ``source``."""
    source = as_packed_frame(source)
    target = as_packed_frame(target)
    if step <= 0:
        return copy_frame(source)
    if step >= steps:
        return copy_frame(target)
    split = source.width * step // steps
    full_bytes = split >> 3
    partial_bits = split & 7
    partial_mask = (1 << partial_bits) - 1
    data = bytearray(len(source.data))
    for y in range(source.height):
        row_base = y * source.stride
        for byte_index in range(source.stride):
            idx = row_base + byte_index
            if byte_index < full_bytes:
                data[idx] = target.data[idx]
            elif byte_index == full_bytes and partial_bits:
                source_mask = 0xFF ^ partial_mask
                data[idx] = (target.data[idx] & partial_mask) | (source.data[idx] & source_mask)
            else:
                data[idx] = source.data[idx]
    return PackedFrame(
        source.width,
        source.height,
        source.stride,
        data,
        max(source.intensity, target.intensity),
    )


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


def scroll_frame(source: object, target: object, step: int, steps: int) -> object:
    """Slide ``source`` left while ``target`` enters from the right."""
    source = as_packed_frame(source)
    target = as_packed_frame(target)
    if step <= 0:
        return copy_frame(source)
    if step >= steps:
        return copy_frame(target)
    offset = source.width * step // steps
    data = bytearray(len(source.data))
    mask = (1 << source.width) - 1
    target_shift = source.width - offset
    for y in range(source.height):
        source_bits = packed_row_bits(source, y) >> offset
        target_bits = (packed_row_bits(target, y) << target_shift) & mask
        write_packed_row_bits(
            data,
            y * source.stride,
            source.stride,
            source_bits | target_bits,
        )
    return PackedFrame(
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
    intensity_limit: float,
) -> object:
    """Fade through masked low-intensity frames into ``target``."""
    if step <= 0:
        return copy_frame(source)
    if step >= steps:
        return copy_frame(target)
    min_visible = min_visible_source_byte(intensity_limit)
    half = steps // 2
    if step <= half:
        visible_steps = half - step
        value = fade_step_value(
            max_frame_value(source),
            visible_steps - 1,
            half - 1,
            min_visible,
        )
        return masked_fade_frame(source, visible_steps, half, value, min_visible)
    visible_steps = step - half
    total_steps = steps - half
    value = fade_step_value(
        max_frame_value(target),
        visible_steps - 1,
        total_steps - 1,
        min_visible,
    )
    return masked_fade_frame(target, visible_steps, total_steps, value, min_visible)


def frame_transition_frame(
    effect: int,
    source: object,
    target: object,
    *,
    step: int,
    steps: int,
    intensity_limit: float,
) -> object:
    """Render one transition frame between two concrete frame endpoints."""
    if effect == TRANSITION_INSTANT:
        return copy_frame(target)
    if effect == TRANSITION_FADE:
        return fade_frame(source, target, step, steps, intensity_limit)
    if effect == TRANSITION_SCROLL:
        return scroll_frame(source, target, step, steps)
    return wipe_frame(source, target, step, steps)


def randbelow(limit: int, rng: object | None = None) -> int:
    """Return a random integer in ``range(limit)`` using a small MCU API."""
    if rng is None:
        rng = random
    return rng.getrandbits(8) % limit


def choose_transition(rng: object | None = None) -> int:
    """Choose one transition effect."""
    return TRANSITIONS[randbelow(len(TRANSITIONS), rng)]
