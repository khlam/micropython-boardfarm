"""Host CPython tests for Provisioner credential rotation and the OLED QR.

Rotation is the one path where the AP's credentials change underneath a QR that
may already be on the panel, so these tests drive the ``absolute_timeout`` event
and compare the pixels actually flushed to the display against an independent
render of the new session's payload.
"""

from __future__ import annotations

import pathlib
import sys

_FIRMWARE_DIR = str(pathlib.Path(__file__).parent.parent / "firmware")
if _FIRMWARE_DIR not in sys.path:
    sys.path.insert(0, _FIRMWARE_DIR)

import provisioning  # noqa: E402
import pytest  # noqa: E402

import qr_code  # noqa: E402

_PAYLOAD_A = "WIFI:T:WPA;S:LEDFX-AAAAAAAA;P:AAAAAAAAAAAAAAAAAAAAAAAB;;"
_PAYLOAD_B = "WIFI:T:WPA;S:LEDFX-BBBBBBBB;P:BBBBBBBBBBBBBBBBBBBBBBBC;;"
_QUIET = 4


def test_rotation_redraws_qr_while_visible(prov, sessions):
    prov.begin()
    prov.show_qr()
    assert prov.display.frames[-1] == _expected_frame(_PAYLOAD_A)

    sessions[0].events = ["absolute_timeout"]
    prov.poll(0)

    assert len(sessions) == 2
    assert prov.display.frames[-1] == _expected_frame(_PAYLOAD_B)


def test_rotation_while_hidden_shows_new_credentials(prov, sessions):
    prov.begin()
    sessions[0].events = ["absolute_timeout"]
    prov.poll(0)
    prov.show_qr()

    assert prov.display.frames[-1] == _expected_frame(_PAYLOAD_B)


def test_rotation_never_leaves_the_old_qr_on_the_panel(prov, sessions):
    prov.begin()
    prov.show_qr()
    stale = _expected_frame(_PAYLOAD_A)

    sessions[0].events = ["absolute_timeout"]
    prov.poll(0)

    # Every flush after the rotation must be the new code (or a blank panel);
    # the old credentials must never be readable again.
    for frame in prov.display.frames[1:]:
        assert frame != stale


def test_complete_event_keeps_the_same_qr(prov, sessions):
    prov.begin()
    prov.show_qr()
    sessions[0].events = ["complete"]
    prov.poll(0)

    assert len(sessions) == 1
    assert prov.display.frames[-1] == _expected_frame(_PAYLOAD_A)


def test_draw_failure_during_rotation_disables_and_blanks(prov, sessions):
    prov.begin()
    prov.show_qr()
    prov.display.fail_shows = 1  # the new session's draw fails, blanking recovers

    sessions[0].events = ["absolute_timeout"]
    prov.poll(0)

    assert not prov.enabled
    assert sessions[-1].stopped
    assert prov.display.frames[-1] == _blank_frame()


def test_rotation_wipes_the_old_session(prov, sessions):
    prov.begin()
    sessions[0].events = ["absolute_timeout"]
    prov.poll(0)

    assert sessions[0].stopped
    assert sessions[1].started


class _FakeDisplay:
    """Minimal SSD1306 stand-in that snapshots its framebuffer on ``show``."""

    width = 128
    height = 64

    def __init__(self) -> None:
        self._buf = [[0] * self.width for _ in range(self.height)]
        self.frames: list[list[list[int]]] = []
        self.fail_shows = 0  # number of upcoming show() calls that raise

    def fill(self, value: int) -> None:
        for row in self._buf:
            for x in range(self.width):
                row[x] = value

    def pixel(self, x: int, y: int, value: int) -> None:
        self._buf[y][x] = value

    def show(self) -> None:
        if self.fail_shows > 0:
            self.fail_shows -= 1
            raise OSError(5)
        self.frames.append([row[:] for row in self._buf])


class _FakeSession:
    """Scripted ``wifi.Session`` stand-in: one payload, a queue of poll events."""

    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.events: list[str] = []
        self.started = False
        self.stopped = False

    def qr_payload(self) -> str:
        return self._payload

    def start(self) -> None:
        self.started = True

    def poll(self, _now_ms: int) -> str | None:
        return self.events.pop(0) if self.events else None

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def sessions(monkeypatch):
    """Replace ``wifi.create_session`` with a scripted two-payload sequence."""
    created: list[_FakeSession] = []
    payloads = [_PAYLOAD_A, _PAYLOAD_B]

    def _create(_config, _handler):
        session = _FakeSession(payloads[len(created) % len(payloads)])
        created.append(session)
        return session

    monkeypatch.setattr(provisioning.wifi, "create_session", _create)
    return created


@pytest.fixture
def prov(sessions):
    """A Provisioner wired to a fake OLED, with its display exposed for asserts."""
    display = _FakeDisplay()
    provisioner = provisioning.Provisioner(
        provisioning.PROV_CONFIG, display, _FakeLedState(), lambda _obj: None
    )
    provisioner.display = display
    return provisioner


class _FakeLedState:
    """LED state stand-in; rotation never touches it."""

    def apply(self, _record: dict) -> None:
        raise AssertionError("rotation must not change the LED mode")


def _blank_frame() -> list[list[int]]:
    """Return the all-dark framebuffer snapshot."""
    return [[0] * _FakeDisplay.width for _ in range(_FakeDisplay.height)]


def _expected_frame(payload: str) -> list[list[int]]:
    """Independently render ``payload`` the way ``_draw_qr`` is specified to."""
    grid = qr_code.encode(payload)
    dim = qr_code.SIZE + 2 * _QUIET
    bx = (_FakeDisplay.width - dim) // 2
    by = (_FakeDisplay.height - dim) // 2
    frame = _blank_frame()
    for yy in range(dim):
        for xx in range(dim):
            frame[by + yy][bx + xx] = 1
    for y in range(qr_code.SIZE):
        for x in range(qr_code.SIZE):
            if grid[y][x]:
                frame[by + _QUIET + y][bx + _QUIET + x] = 0
    return frame
