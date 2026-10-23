"""Behavioral tests for packed-frame transitions and their random selection."""

from __future__ import annotations

from itertools import pairwise

import pytest
from fake_clock import FakeRandom, lit_pixels, same_frame

import clock_transitions as ct
from pixel_frame import Frame

_STEPS = 8
_W = 10
_H = 6
_ANIMATED = (ct.TRANSITION_WIPE, ct.TRANSITION_DISSOLVE, ct.TRANSITION_SCROLL)
_SOURCE_PIXELS = {(1, 1), (2, 4), (7, 2), (9, 5)}
_TARGET_PIXELS = {(0, 0), (3, 4), (6, 1), (8, 5)}


@pytest.mark.parametrize("effect", ct.TRANSITIONS)
@pytest.mark.parametrize("step", [-1, 0, _STEPS, _STEPS + 1])
def test_effects_clamp_to_independent_endpoint_copies(effect: int, step: int) -> None:
    source, target = _endpoints()
    source_before, target_before = source.copy(), target.copy()

    frame = ct.frame_transition_frame(
        effect, source, target, step=step, steps=_STEPS, direction=ct.DIRECTION_LEFT
    )

    expected = target if effect == ct.TRANSITION_INSTANT or step >= _STEPS else source
    assert same_frame(frame, expected)
    frame.pixel(0, 1)
    assert same_frame(source, source_before)
    assert same_frame(target, target_before)


@pytest.mark.parametrize("effect", _ANIMATED)
@pytest.mark.parametrize(
    "source_intensity,target_intensity",
    [(47, 133), (133, 47)],
    ids=["target-brighter", "source-brighter"],
)
def test_animation_preserves_endpoints_and_uses_the_brighter_intensity(
    effect: int, source_intensity: int, target_intensity: int
) -> None:
    """Both orderings, so `max(source, target)` is not satisfied by either alone.

    The panel carries one global brightness, so an intermediate frame mixing two
    endpoints has to take the brighter of the two or the outgoing screen visibly
    dims mid-transition.
    """
    source, target = _endpoints(source_intensity, target_intensity)
    source_before, target_before = source.copy(), target.copy()
    brighter = max(source_intensity, target_intensity)

    for step in range(1, _STEPS):
        frame = ct.frame_transition_frame(
            effect, source, target, step=step, steps=_STEPS, direction=ct.DIRECTION_TOP_LEFT
        )
        assert frame.intensity == brighter
        assert (frame.width, frame.height) == (_W, _H)

    assert same_frame(source, source_before)
    assert same_frame(target, target_before)


@pytest.mark.parametrize("direction", ct.DIRECTIONS)
def test_wipe_reveals_pixels_without_flickering_back(direction: int) -> None:
    source = Frame(_W, _H)
    target = _filled_frame(_W, _H)

    revealed = [
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
        for step in range(_STEPS + 1)
    ]

    assert revealed[0] == set()
    assert revealed[-1] == lit_pixels(target)
    assert 0 < len(revealed[_STEPS // 2]) < _W * _H
    for earlier, later in pairwise(revealed):
        assert earlier <= later


@pytest.mark.parametrize(
    "direction,expected",
    [
        (ct.DIRECTION_LEFT, {(0, y) for y in range(_H)}),
        (ct.DIRECTION_RIGHT, {(_W - 1, y) for y in range(_H)}),
        (ct.DIRECTION_TOP, {(x, 0) for x in range(_W)}),
        (ct.DIRECTION_BOTTOM, {(x, _H - 1) for x in range(_W)}),
        (ct.DIRECTION_TOP_LEFT, {(0, 0)}),
        (ct.DIRECTION_TOP_RIGHT, {(_W - 1, 0)}),
        (ct.DIRECTION_BOTTOM_LEFT, {(0, _H - 1)}),
        (ct.DIRECTION_BOTTOM_RIGHT, {(_W - 1, _H - 1)}),
    ],
)
def test_wipe_enters_only_from_the_named_edge_or_corner(direction: int, expected: set) -> None:
    frame = ct.frame_transition_frame(
        ct.TRANSITION_WIPE,
        Frame(_W, _H),
        _filled_frame(_W, _H),
        step=1,
        steps=20,
        direction=direction,
    )

    assert lit_pixels(frame) == expected


def test_dissolve_flips_a_stable_scattered_share_of_pixels_each_step() -> None:
    source = _filled_frame(16, 8)
    target = Frame(16, 8)
    remaining = [
        lit_pixels(
            ct.frame_transition_frame(
                ct.TRANSITION_DISSOLVE,
                source,
                target,
                step=step,
                steps=_STEPS,
                direction=ct.DIRECTION_LEFT,
            )
        )
        for step in range(_STEPS + 1)
    ]

    assert [len(pixels) for pixels in remaining] == [128, 112, 96, 80, 64, 48, 32, 16, 0]
    for earlier, later in pairwise(remaining):
        assert later <= earlier
    assert all(0 < sum(y == row for _x, y in remaining[4]) < 16 for row in range(8))
    repeated = ct.frame_transition_frame(
        ct.TRANSITION_DISSOLVE, source, target, step=4, steps=_STEPS, direction=ct.DIRECTION_LEFT
    )
    assert lit_pixels(repeated) == remaining[4]


@pytest.mark.parametrize("effect", [ct.TRANSITION_WIPE, ct.TRANSITION_DISSOLVE])
def test_reveals_preserve_pixels_shared_by_both_endpoints(effect: int) -> None:
    source, target = _endpoints()
    source.pixel(4, 3)
    target.pixel(4, 3)
    allowed = lit_pixels(source) | lit_pixels(target)

    for step in range(1, _STEPS):
        frame = ct.frame_transition_frame(
            effect, source, target, step=step, steps=_STEPS, direction=ct.DIRECTION_LEFT
        )
        assert (4, 3) in lit_pixels(frame)
        assert lit_pixels(frame) <= allowed


@pytest.mark.parametrize(
    "direction,expected",
    [
        (ct.DIRECTION_LEFT, {(6, 1), (7, 4), (1, 1), (3, 5)}),
        (ct.DIRECTION_RIGHT, {(2, 2), (4, 5), (5, 0), (8, 4)}),
        (ct.DIRECTION_TOP, {(1, 4), (7, 5), (3, 1), (8, 2)}),
        (ct.DIRECTION_BOTTOM, {(2, 1), (9, 2), (0, 3), (6, 4)}),
        (ct.DIRECTION_TOP_LEFT, {(6, 4), (3, 2)}),
        (ct.DIRECTION_TOP_RIGHT, {(2, 5), (8, 1)}),
        (ct.DIRECTION_BOTTOM_LEFT, {(7, 1), (1, 4)}),
        (ct.DIRECTION_BOTTOM_RIGHT, {(4, 2), (5, 3)}),
    ],
)
def test_scroll_translates_both_endpoints_and_clips_at_each_edge(
    direction: int, expected: set
) -> None:
    """Halfway through a 10x6 scroll, movement is five columns and/or three rows."""
    source, target = _endpoints()

    frame = ct.frame_transition_frame(
        ct.TRANSITION_SCROLL,
        source,
        target,
        step=4,
        steps=8,
        direction=direction,
    )

    assert lit_pixels(frame) == expected


def test_unknown_effect_falls_back_to_a_wipe() -> None:
    source, target = _endpoints()
    box = {"step": 3, "steps": _STEPS, "direction": ct.DIRECTION_LEFT}

    unknown = ct.frame_transition_frame(99, source, target, **box)
    wipe = ct.frame_transition_frame(ct.TRANSITION_WIPE, source, target, **box)

    assert same_frame(unknown, wipe)


def test_random_selection_can_reach_every_effect_and_direction() -> None:
    assert {ct.choose_transition(FakeRandom([n])) for n in range(256)} == set(ct.TRANSITIONS)
    assert {ct.choose_direction(FakeRandom([n])) for n in range(256)} == set(ct.DIRECTIONS)


@pytest.mark.parametrize("effect", [ct.TRANSITION_WIPE, ct.TRANSITION_DISSOLVE])
def test_cached_reveals_remain_correct_after_other_geometries_and_step_counts(effect: int) -> None:
    original = None
    for width, height, steps in [(10, 6, 8), (9, 7, 8), (10, 6, 4), (10, 6, 8)]:
        target = _filled_frame(width, height)
        frame = ct.frame_transition_frame(
            effect,
            Frame(width, height),
            target,
            step=steps // 2,
            steps=steps,
            direction=ct.DIRECTION_LEFT,
        )
        assert (frame.width, frame.height) == (width, height)
        if effect == ct.TRANSITION_WIPE:
            assert lit_pixels(frame) == {(x, y) for x in range(width // 2) for y in range(height)}
        else:
            assert len(lit_pixels(frame)) == width * height // 2
        if original is None:
            original = frame
    assert same_frame(frame, original)


def _endpoints(source_intensity: int = 47, target_intensity: int = 133) -> tuple:
    """Return asymmetric endpoints spanning a partial final packed byte."""
    source = Frame(_W, _H, intensity=source_intensity)
    target = Frame(_W, _H, intensity=target_intensity)
    for x, y in _SOURCE_PIXELS:
        source.pixel(x, y)
    for x, y in _TARGET_PIXELS:
        target.pixel(x, y)
    return source, target


def _filled_frame(width: int, height: int) -> Frame:
    """Return a fully lit frame."""
    frame = Frame(width, height)
    for y in range(height):
        for x in range(width):
            frame.pixel(x, y)
    return frame
