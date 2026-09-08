"""Packed frame transition effects for clock screens."""

from pixel_frame import Frame

TRANSITION_WIPE = 0
TRANSITION_DISSOLVE = 1
TRANSITION_SCROLL = 2
TRANSITION_INSTANT = 3
TRANSITIONS = (
    TRANSITION_WIPE,
    TRANSITION_DISSOLVE,
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
# Entry vector per direction: the axis signs pointing away from the edge the
# incoming content enters from. A zero component means that axis is stationary.
_DELTAS = {
    DIRECTION_LEFT: (-1, 0),
    DIRECTION_RIGHT: (1, 0),
    DIRECTION_TOP: (0, -1),
    DIRECTION_BOTTOM: (0, 1),
    DIRECTION_TOP_LEFT: (-1, -1),
    DIRECTION_TOP_RIGHT: (1, -1),
    DIRECTION_BOTTOM_LEFT: (-1, 1),
    DIRECTION_BOTTOM_RIGHT: (1, 1),
}
_DIRECTION_MASKS = {}
_RANDOM_DISSOLVE_MASKS = {}
_DISSOLVE_SEED = 0x9E3779B1


def _direction_masks(
    width: int,
    height: int,
    total_steps: int,
    direction: int,
) -> tuple:
    """Return cached directional masks for the intermediate transition steps."""
    key = (width, height, total_steps, direction)
    cached = _DIRECTION_MASKS.get(key)
    if cached is not None:
        return cached
    stride = (width + 7) // 8
    dx, dy = _DELTAS[direction]
    total_ranks = 1 + (width - 1 if dx else 0) + (height - 1 if dy else 0)
    masks = []
    for visible_steps in range(1, total_steps):
        data = bytearray(height * stride)
        visible_ranks = max(1, total_ranks * visible_steps // total_steps)
        for y in range(height):
            row_base = y * stride
            row_rank = _axis_rank(dy, height, y)
            for x in range(width):
                rank = row_rank + _axis_rank(dx, width, x)
                if rank < visible_ranks:
                    data[row_base + (x >> 3)] |= 1 << (x & 7)
        masks.append(data)
    cached = tuple(masks)
    _DIRECTION_MASKS[key] = cached
    return cached


def _axis_rank(delta: int, length: int, position: int) -> int:
    """Return distance from an entry edge, or zero for a stationary axis."""
    if delta < 0:
        return position
    if delta > 0:
        return length - 1 - position
    return 0


def _mixed_mask_frame(source: object, target: object, mask: bytearray) -> object:
    """Return ``source`` and ``target`` composited through a packed mask."""
    data = bytearray(len(source.data))
    for i, item in enumerate(mask):
        data[i] = (target.data[i] & item) | (source.data[i] & (0xFF ^ item))
    return Frame(
        source.width,
        source.height,
        max(source.intensity, target.intensity),
        stride=source.stride,
        data=data,
    )


def _shuffled_pixel_order(width: int, height: int, seed: int) -> list:
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


def _dissolve_masks(width: int, height: int, total: int) -> tuple:
    """Return cached cumulative dissolve masks for intermediate transition steps.

    ``masks[k - 1]`` reveals the first ``k / total`` of the shuffled pixels.
    Endpoints need no masks because the renderer copies their frames directly.
    """
    key = (width, height, total)
    cached = _RANDOM_DISSOLVE_MASKS.get(key)
    if cached is not None:
        return cached
    stride = (width + 7) // 8
    order = _shuffled_pixel_order(width, height, _DISSOLVE_SEED)
    pixel_count = width * height
    data = bytearray(height * stride)
    masks = []
    placed = 0
    for visible_steps in range(1, total):
        target_count = visible_steps * pixel_count // total
        while placed < target_count:
            index = order[placed]
            x = index % width
            y = index // width
            data[(y * stride) + (x >> 3)] |= 1 << (x & 7)
            placed += 1
        masks.append(bytes(data))
    cached = tuple(masks)
    _RANDOM_DISSOLVE_MASKS[key] = cached
    return cached


def _packed_row_bits(frame: object, y: int) -> int:
    """Return one packed row as a little-endian integer."""
    base = y * frame.stride
    return int.from_bytes(frame.data[base : base + frame.stride], "little")


def _shifted_row_bits(bits: int, width: int, offset: int, dx: int) -> int:
    """Shift packed row bits by ``offset`` pixels opposite ``dx``."""
    mask = (1 << width) - 1
    if dx < 0:
        return (bits << offset) & mask
    if dx > 0:
        return bits >> offset
    return bits & mask


def _scroll_frame(
    source: object,
    target: object,
    step: int,
    steps: int,
    direction: int,
) -> object:
    """Slide packed ``target`` in from ``direction``."""
    data = bytearray(len(source.data))
    dx, dy = _DELTAS[direction]
    offset_x = source.width * step // steps if dx else 0
    offset_y = source.height * step // steps if dy else 0
    target_y = dy * (source.height - offset_y)
    for y in range(source.height):
        bits = 0
        source_y = y + dy * offset_y
        if 0 <= source_y < source.height:
            bits |= _shifted_row_bits(
                _packed_row_bits(source, source_y),
                source.width,
                offset_x,
                dx,
            )
        target_sample_y = y - target_y
        if 0 <= target_sample_y < target.height:
            bits |= _shifted_row_bits(
                _packed_row_bits(target, target_sample_y),
                source.width,
                source.width - offset_x,
                -dx,
            )
        base = y * source.stride
        data[base : base + source.stride] = bits.to_bytes(source.stride, "little")
    return Frame(
        source.width,
        source.height,
        max(source.intensity, target.intensity),
        stride=source.stride,
        data=data,
    )


def frame_transition_frame(
    effect: int,
    source: object,
    target: object,
    *,
    step: int,
    steps: int,
    direction: int,
) -> object:
    """Render one transition frame between two packed frame endpoints."""
    if effect == TRANSITION_INSTANT:
        return target.copy()
    if step <= 0:
        return source.copy()
    if step >= steps:
        return target.copy()
    if effect == TRANSITION_SCROLL:
        return _scroll_frame(source, target, step, steps, direction)
    if effect == TRANSITION_DISSOLVE:
        # Binary pixel swaps stay visible even at low global brightness.
        masks = _dissolve_masks(source.width, source.height, steps)
    else:
        masks = _direction_masks(source.width, source.height, steps, direction)
    return _mixed_mask_frame(source, target, masks[step - 1])


def randbelow(limit: int, rng: object) -> int:
    """Return a random integer in ``range(limit)`` using a small MCU API."""
    return rng.getrandbits(8) % limit


def choose_transition(rng: object) -> int:
    """Choose one transition effect."""
    return TRANSITIONS[randbelow(len(TRANSITIONS), rng)]


def choose_direction(rng: object) -> int:
    """Choose one transition entry direction."""
    return DIRECTIONS[randbelow(len(DIRECTIONS), rng)]
