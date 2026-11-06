"""Seven-segment glyphs for a digit built from a chain of addressable LEDs.

Segment letters follow this board's own labels, not the common a-is-top
convention: b top, a upper right, f lower right, e bottom, d lower left,
c upper left, g middle. No hardware dependency — the caller latches the
returned frame to its LEDs.
"""

# Lit segments for each digit 0-9, indexed by the digit.
DIGIT_SEGMENTS = (
    "abcdef",
    "af",
    "abdeg",
    "abefg",
    "acfg",
    "bcefg",
    "bcdefg",
    "abf",
    "abcdefg",
    "abcefg",
)


def digit_frame(
    digit: int,
    *,
    chain_order: str,
    leds_per_segment: int,
    on: tuple[int, int, int],
    off: tuple[int, int, int],
) -> list[tuple[int, int, int]]:
    """Return one RGB tuple per LED that shows `digit` on the chain.

    Args:
        digit: Value to show, 0-9.
        chain_order: Segment letters in the order the data line visits them.
        leds_per_segment: LEDs wired in series within each segment.
        on: Colour of the LEDs in lit segments.
        off: Colour of the LEDs in dark segments.

    Returns:
        ``len(chain_order) * leds_per_segment`` colours in chain order.

    Raises:
        ValueError: `digit` is outside 0-9.
    """
    if not 0 <= digit < len(DIGIT_SEGMENTS):
        raise ValueError(f"digit must be 0-9, got {digit}")
    lit = DIGIT_SEGMENTS[digit]
    frame = []
    for segment in chain_order:
        frame.extend([on if segment in lit else off] * leds_per_segment)
    return frame
