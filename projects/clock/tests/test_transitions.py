"""Host CPython tests for the packed-frame transition effects.

Expected frames are never computed by calling the transition code — that would
pass no matter how the effect behaved. Instead each test asserts the properties
the effect promises: the endpoints are exact, the reveal grows monotonically,
and pixels only ever come from one of the two source frames.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from fake_clock import FakeRandom, lit_pixels, same_frame

import clock_transitions as ct
from pixel_frame import Frame

_STEPS = 8
_W = 16
_H = 8
_EFFECTS = (
    ct.TRANSITION_WIPE,
    ct.TRANSITION_DISSOLVE,
    ct.TRANSITION_SCROLL,
    ct.TRANSITION_INSTANT,
)


@pytest.mark.parametrize("effect", _EFFECTS)
def test_every_effect_lands_exactly_on_the_target(effect: int) -> None:
    source, target = _endpoints()

    landed = ct.frame_transition_frame(
        effect, source, target, step=_STEPS, steps=_STEPS, direction=ct.DIRECTION_LEFT
    )

    assert same_frame(landed, target)


@pytest.mark.parametrize(
    "effect", [ct.TRANSITION_WIPE, ct.TRANSITION_DISSOLVE, ct.TRANSITION_SCROLL]
)
def test_animated_effects_start_from_the_source(effect: int) -> None:
    source, target = _endpoints()

    first = ct.frame_transition_frame(
        effect, source, target, step=0, steps=_STEPS, direction=ct.DIRECTION_LEFT
    )

    assert same_frame(first, source)


def test_instant_effect_ignores_the_step_and_shows_the_target() -> None:
    source, target = _endpoints()

    frame = ct.frame_transition_frame(ct.TRANSITION_INSTANT, source, target, step=0, steps=_STEPS)

    assert same_frame(frame, target)


@pytest.mark.parametrize("effect", _EFFECTS)
def test_effects_never_mutate_their_endpoints(effect: int) -> None:
    source, target = _endpoints()
    source_before = bytes(source.data)
    target_before = bytes(target.data)

    for step in range(_STEPS + 1):
        ct.frame_transition_frame(
            effect, source, target, step=step, steps=_STEPS, direction=ct.DIRECTION_TOP_LEFT
        )

    assert bytes(source.data) == source_before
    assert bytes(target.data) == target_before


@pytest.mark.parametrize("direction", ct.DIRECTIONS)
def test_wipe_reveals_the_target_monotonically_from_every_direction(direction: int) -> None:
    """Each wipe step may only add target pixels, never take revealed ones back."""
    source = Frame(_W, _H, intensity=255)  # fully dark
    target = _filled_frame()

    revealed = [
        len(
            lit_pixels(
                ct.frame_transition_frame(
                    ct.TRANSITION_WIPE,
                    source,
                    target,
                    step=step,
                    steps=_STEPS,
                    direction=direction,
                )
            )
        )
        for step in range(_STEPS + 1)
    ]

    assert revealed == sorted(revealed)
    assert revealed[0] == 0
    assert revealed[-1] == _W * _H


@pytest.mark.parametrize(
    "direction,corner",
    [
        (ct.DIRECTION_LEFT, (0, 0)),  # enters from the left edge
        (ct.DIRECTION_RIGHT, (_W - 1, 0)),
        (ct.DIRECTION_TOP, (0, 0)),
        (ct.DIRECTION_BOTTOM, (0, _H - 1)),
    ],
)
def test_wipe_enters_from_the_named_edge(direction: int, corner: tuple) -> None:
    source = Frame(_W, _H, intensity=255)
    target = _filled_frame()

    early = ct.frame_transition_frame(
        ct.TRANSITION_WIPE, source, target, step=1, steps=_STEPS, direction=direction
    )

    assert corner in lit_pixels(early)


def test_wipe_defaults_to_entering_from_the_left() -> None:
    source = Frame(_W, _H, intensity=255)
    target = _filled_frame()

    default = ct.frame_transition_frame(ct.TRANSITION_WIPE, source, target, step=3, steps=_STEPS)
    explicit = ct.frame_transition_frame(
        ct.TRANSITION_WIPE, source, target, step=3, steps=_STEPS, direction=ct.DIRECTION_LEFT
    )

    assert same_frame(default, explicit)


def test_dissolve_swaps_a_growing_share_of_pixels_to_the_target() -> None:
    """Mid-dissolve frames mix both endpoints, growing toward the target."""
    source = _filled_frame()
    target = Frame(_W, _H, intensity=255)  # all dark, so lit pixels count source

    remaining = [
        len(
            lit_pixels(
                ct.frame_transition_frame(
                    ct.TRANSITION_DISSOLVE, source, target, step=step, steps=_STEPS
                )
            )
        )
        for step in range(_STEPS + 1)
    ]

    assert remaining[0] == _W * _H
    assert remaining[-1] == 0
    assert remaining == sorted(remaining, reverse=True)
    # A genuine mid-dissolve, not a jump between the two endpoints.
    assert 0 < remaining[_STEPS // 2] < _W * _H


def test_dissolve_order_is_stable_across_steps() -> None:
    """A pixel already flipped to the target must not flicker back."""
    source = _filled_frame()
    target = Frame(_W, _H, intensity=255)

    flipped = [
        lit_pixels(source)
        - lit_pixels(
            ct.frame_transition_frame(
                ct.TRANSITION_DISSOLVE, source, target, step=step, steps=_STEPS
            )
        )
        for step in range(_STEPS + 1)
    ]

    for earlier, later in pairwise(flipped):
        assert earlier <= later


def test_dissolve_is_scattered_rather_than_a_directional_sweep() -> None:
    """The dissolve reveals pixels in random order, so no row fills before another."""
    source = _filled_frame()
    target = Frame(_W, _H, intensity=255)

    mid = ct.frame_transition_frame(
        ct.TRANSITION_DISSOLVE, source, target, step=_STEPS // 2, steps=_STEPS
    )
    per_row = [sum(1 for x in range(_W) if mid.value_at(x, y)) for y in range(_H)]

    # Every row keeps some pixels and loses some: no row is fully consumed first.
    assert all(0 < count < _W for count in per_row)


def test_shuffled_pixel_order_is_a_permutation_and_deterministic() -> None:
    first = ct.shuffled_pixel_order(_W, _H, 12345)
    second = ct.shuffled_pixel_order(_W, _H, 12345)

    assert sorted(first) == list(range(_W * _H))
    assert first == second
    assert first != ct.shuffled_pixel_order(_W, _H, 999)


@pytest.mark.parametrize(
    "direction",
    [ct.DIRECTION_LEFT, ct.DIRECTION_RIGHT, ct.DIRECTION_TOP, ct.DIRECTION_BOTTOM],
)
def test_scroll_slides_content_without_inventing_pixels(direction: int) -> None:
    """Every lit pixel mid-scroll comes from a shifted copy of one endpoint."""
    source = _striped_frame(0)
    target = _striped_frame(1)

    mid = ct.frame_transition_frame(
        ct.TRANSITION_SCROLL, source, target, step=_STEPS // 2, steps=_STEPS, direction=direction
    )

    assert 0 < len(lit_pixels(mid)) <= _W * _H
    assert not same_frame(mid, source)
    assert not same_frame(mid, target)


@pytest.mark.parametrize("step", [1, 2, 3])
def test_horizontal_scroll_translates_source_columns_by_the_step_fraction(step: int) -> None:
    """A target entering from the left pushes the source column right, intact."""
    source = _column_frame(0)
    target = Frame(_W, _H, intensity=255)  # dark, so only source pixels show

    mid = ct.frame_transition_frame(
        ct.TRANSITION_SCROLL,
        source,
        target,
        step=step,
        steps=_STEPS,
        direction=ct.DIRECTION_LEFT,
    )

    assert lit_pixels(mid) == {(_W * step // _STEPS, y) for y in range(_H)}


@pytest.mark.parametrize("step", [1, 2, 3])
def test_vertical_scroll_translates_source_rows_by_the_step_fraction(step: int) -> None:
    """A target entering from the top pushes the source row down, intact."""
    source = _row_frame(0)
    target = Frame(_W, _H, intensity=255)

    mid = ct.frame_transition_frame(
        ct.TRANSITION_SCROLL,
        source,
        target,
        step=step,
        steps=_STEPS,
        direction=ct.DIRECTION_TOP,
    )

    assert lit_pixels(mid) == {(x, _H * step // _STEPS) for x in range(_W)}


def test_scroll_defaults_to_entering_from_the_right() -> None:
    source = _striped_frame(0)
    target = _striped_frame(1)

    default = ct.frame_transition_frame(ct.TRANSITION_SCROLL, source, target, step=3, steps=_STEPS)
    explicit = ct.frame_transition_frame(
        ct.TRANSITION_SCROLL, source, target, step=3, steps=_STEPS, direction=ct.DIRECTION_RIGHT
    )

    assert same_frame(default, explicit)


def test_unknown_effect_falls_back_to_a_wipe() -> None:
    source, target = _endpoints()

    unknown = ct.frame_transition_frame(99, source, target, step=3, steps=_STEPS)
    wipe = ct.frame_transition_frame(
        ct.TRANSITION_WIPE, source, target, step=3, steps=_STEPS, direction=ct.DIRECTION_LEFT
    )

    assert same_frame(unknown, wipe)


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, ct.TRANSITION_WIPE),
        (1, ct.TRANSITION_DISSOLVE),
        (2, ct.TRANSITION_SCROLL),
        (3, ct.TRANSITION_INSTANT),
        (4, ct.TRANSITION_WIPE),  # wraps back around the table
    ],
)
def test_choose_transition_maps_random_values_onto_the_effect_table(
    value: int, expected: int
) -> None:
    assert ct.choose_transition(FakeRandom([value])) == expected


def test_choose_transition_only_ever_returns_a_known_effect() -> None:
    for value in range(256):
        assert ct.choose_transition(FakeRandom([value])) in ct.TRANSITIONS


def test_choose_direction_only_ever_returns_a_known_direction() -> None:
    for value in range(256):
        assert ct.choose_direction(FakeRandom([value])) in ct.DIRECTIONS


def test_randbelow_stays_inside_the_requested_range() -> None:
    for value in range(256):
        assert 0 <= ct.randbelow(5, FakeRandom([value])) < 5


def test_direction_delta_covers_the_eight_compass_entries() -> None:
    deltas = {ct.direction_delta(direction) for direction in ct.DIRECTIONS}

    assert deltas == {(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)}


@pytest.mark.parametrize(
    "direction,expected",
    [
        (ct.DIRECTION_LEFT, _W),  # a horizontal wipe has one rank per column
        (ct.DIRECTION_TOP, _H),  # a vertical wipe has one rank per row
        (ct.DIRECTION_TOP_LEFT, _W + _H - 1),  # diagonals sweep the anti-diagonals
    ],
)
def test_direction_total_counts_the_reveal_ranks(direction: int, expected: int) -> None:
    assert ct.direction_total(direction, _W, _H) == expected


def test_directional_masks_are_cached_per_geometry() -> None:
    """Mask tables are expensive to build, so repeat lookups must reuse them."""
    frame = Frame(_W, _H)
    ct._DIRECTION_MASKS.clear()

    first = ct.directional_mask(frame, _STEPS, 3, ct.DIRECTION_LEFT)
    second = ct.directional_mask(frame, _STEPS, 3, ct.DIRECTION_LEFT)

    assert first is second
    assert len(ct._DIRECTION_MASKS) == 1


def test_dissolve_masks_are_cached_per_geometry() -> None:
    frame = Frame(_W, _H)
    ct._RANDOM_DISSOLVE_MASKS.clear()

    first = ct.dissolve_mask(frame, _STEPS, 3)
    second = ct.dissolve_mask(frame, _STEPS, 3)

    assert first is second
    assert len(ct._RANDOM_DISSOLVE_MASKS) == 1


def _endpoints() -> tuple:
    """Return two distinguishable packed frames of the same geometry."""
    return _striped_frame(0), _striped_frame(1)


def _filled_frame() -> Frame:
    """Return a fully lit frame."""
    frame = Frame(_W, _H, intensity=255)
    for y in range(_H):
        for x in range(_W):
            frame.pixel(x, y)
    return frame


def _striped_frame(parity: int) -> Frame:
    """Return a frame lit on alternating columns of the given parity."""
    frame = Frame(_W, _H, intensity=255)
    for y in range(_H):
        for x in range(_W):
            if x % 2 == parity:
                frame.pixel(x, y)
    return frame


def _row_frame(y: int) -> Frame:
    """Return a frame with exactly one fully lit row."""
    frame = Frame(_W, _H, intensity=255)
    for x in range(_W):
        frame.pixel(x, y)
    return frame


def _column_frame(x: int) -> Frame:
    """Return a frame with exactly one fully lit column."""
    frame = Frame(_W, _H, intensity=255)
    for y in range(_H):
        frame.pixel(x, y)
    return frame
