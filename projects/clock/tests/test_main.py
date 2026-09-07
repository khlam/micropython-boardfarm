"""Host CPython tests for the clock firmware entry point and screen sequence.

main.py owns three things the other modules deliberately do not: the BOARD pin
table, the order screens step through, and the two recovery loops (init retry
and the guarded program restart).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fake_clock import (
    AdvancingTime,
    CountdownTime,
    FakeDisplay,
    FakeGPS,
    FakeRandom,
    FakeRTC,
    StopLoop,
)

import clock_hardware
import clock_runtime
import clock_screens

_RMC_FIX = "$GPRMC,235958,A,3723.2475,N,12158.3416,W,0.0,0.0,230626,0.0,E*69"


def test_board_table_is_wired_for_every_supported_chip(main_module: object) -> None:
    """Each board must name distinct SPI and UART pins on the same 32x16 surface."""
    board = main_module.BOARD

    assert board.display.surface.width_pixels == 32
    assert board.display.surface.height_pixels == 16
    pins = (board.display.sck, board.display.mosi, board.display.cs)
    assert len(set(pins)) == len(pins)
    assert board.uart.tx != board.uart.rx


def test_hardware_opens_devices_with_the_boards_pins() -> None:
    board = SimpleNamespace(
        uart=SimpleNamespace(bus_id=0, tx=0, rx=1),
        display=SimpleNamespace(
            spi_id=1,
            sck=26,
            mosi=27,
            cs=28,
            surface=SimpleNamespace(width_pixels=32, height_pixels=16, brightness=0.2),
        ),
    )
    created: dict = {}

    def _display(**kwargs: object) -> FakeDisplay:
        created["display"] = dict(kwargs)
        return FakeDisplay()

    def _gps(**kwargs: object) -> FakeGPS:
        created["gps"] = dict(kwargs)
        return FakeGPS()

    hardware = clock_hardware.ClockHardware(board, _display, _gps, FakeRTC)
    devices = hardware.open()

    assert created["display"] == {
        "spi_id": 1,
        "sck": 26,
        "mosi": 27,
        "cs": 28,
        "width_pixels": 32,
        "height_pixels": 16,
        "brightness": 0.2,
    }
    assert created["gps"] == {"bus_id": 0, "tx": 0, "rx": 1}
    assert devices.display is hardware.display
    assert isinstance(devices.rtc, FakeRTC)


def test_flip_display_is_a_no_op_before_the_devices_open() -> None:
    """The BOOT button is live from boot, before any display exists to flip."""
    hardware = clock_hardware.ClockHardware(
        _BOARD, lambda **_kw: FakeDisplay(), lambda **_kw: FakeGPS(), FakeRTC
    )

    hardware.flip_display()  # must not raise
    devices = hardware.open()
    hardware.flip_display()

    assert devices.display.flips == 1


def test_a_failed_open_clears_the_stale_display_reference() -> None:
    """A half-open retry must not flip a display from the previous attempt."""
    hardware = clock_hardware.ClockHardware(
        _BOARD, lambda **_kw: FakeDisplay(), lambda **_kw: FakeGPS(), FakeRTC
    )
    hardware.open()

    hardware._gps_cls = _raise_os_error
    with pytest.raises(OSError):
        hardware.open()

    assert hardware.display is None
    hardware.flip_display()  # must not raise


def test_pump_gps_feeds_every_line_to_the_synchronizer() -> None:
    sync = _RecordingSync()
    gps = FakeGPS([_RMC_FIX, None])
    clock = CountdownTime(stop_after=2)

    _run_until_stop(clock_runtime.pump_gps(gps, sync), clock)

    assert sync.consumed[0] == _RMC_FIX


def test_pump_gps_survives_a_read_error(status: object) -> None:
    """A NACKing GPS flashes the error LED but must never kill the pump."""
    sync = _RecordingSync()
    gps = FakeGPS([OSError("bus"), _RMC_FIX])
    clock = CountdownTime(stop_after=3)

    _run_until_stop(clock_runtime.pump_gps(gps, sync), clock)

    assert sync.consumed == [_RMC_FIX]  # the good line still landed
    assert "read_err" in status.calls


def test_clock_program_waits_for_a_fix_before_showing_a_clock_face(
    main_module: object,
) -> None:
    """Until GPS syncs, the sequence loops on the wait screen and shows no clock."""
    engine = _RecordingEngine()
    sync = SimpleNamespace(synced=False)

    with pytest.raises(StopLoop):
        asyncio.run(
            main_module.clock_program(engine, sync, FakeRandom([0]), AdvancingTime()),
        )

    assert clock_screens.WAIT_ON in engine.targets
    assert not (set(engine.targets) & set(clock_screens.REGULAR_SCREENS))


def test_clock_program_reveals_a_clock_face_once_synced(main_module: object) -> None:
    engine = _RecordingEngine()
    sync = SimpleNamespace(synced=True)

    with pytest.raises(StopLoop):
        asyncio.run(
            main_module.clock_program(engine, sync, FakeRandom([0]), AdvancingTime()),
        )

    # Diagnostics first, then the brand handoff, then regular faces.
    assert engine.targets[0] == clock_screens.SCREEN_BRAND
    assert set(engine.targets) & set(clock_screens.REGULAR_SCREENS)


def test_clock_program_alternates_regular_faces_with_interstitials(
    main_module: object,
) -> None:
    engine = _RecordingEngine(stop_after=8)
    sync = SimpleNamespace(synced=True)

    with pytest.raises(StopLoop):
        asyncio.run(
            main_module.clock_program(engine, sync, FakeRandom([0, 1, 2]), AdvancingTime()),
        )

    cycle = engine.targets[2:]  # skip the brand handoff and first reveal
    kinds = [clock_screens.screen_spec(target).kind for target in cycle]
    assert clock_screens.KIND_INTERSTITIAL in kinds
    assert clock_screens.KIND_REGULAR in kinds


def test_guarded_program_restarts_the_sequence_after_a_render_error(
    main_module: object, status: object
) -> None:
    """A render glitch must heal the LED and restart, never stop the clock."""
    attempts = {"n": 0}

    async def _failing(*_args: object) -> None:
        attempts["n"] += 1
        if attempts["n"] >= 3:
            raise StopLoop
        raise ValueError("render glitch")

    main_module.clock_program = _failing

    with pytest.raises(StopLoop):
        asyncio.run(
            main_module.guarded_program(
                _RecordingEngine(), SimpleNamespace(synced=True), FakeRandom([0]), AdvancingTime()
            ),
        )

    assert attempts["n"] == 3
    assert "read_err" in status.calls
    assert "streaming" in status.calls


def test_main_retries_after_an_init_failure(main_module: object, status: object) -> None:
    """A missing GPS at boot flashes the init LED and retries rather than halting."""
    attempts = {"n": 0}

    def _gps(**_kwargs: object) -> FakeGPS:
        attempts["n"] += 1
        if attempts["n"] >= 2:
            raise StopLoop
        raise OSError("no gps")

    main_module.MAX7219 = lambda **_kw: FakeDisplay()
    main_module.GPS = _gps
    main_module.RTC = FakeRTC

    with pytest.raises(StopLoop):
        main_module.main()

    assert attempts["n"] == 2
    assert "init_err" in status.calls


def test_main_registers_the_boot_button_for_display_flips(main_module: object) -> None:
    registered: list = []
    main_module.button.on_press = registered.append
    main_module.MAX7219 = lambda **_kw: FakeDisplay()
    main_module.GPS = _raise_stop_loop
    main_module.RTC = FakeRTC

    with pytest.raises(StopLoop):
        main_module.main()

    assert len(registered) == 1
    assert registered[0].__name__ == "flip_display"


def test_main_hands_the_opened_devices_to_the_runtime(main_module: object) -> None:
    received: dict = {}

    def _run(gps: object, display: object, rtc: object) -> None:
        received["devices"] = (gps, display, rtc)
        raise StopLoop

    main_module.MAX7219 = lambda **_kw: FakeDisplay()
    main_module.GPS = lambda **_kw: FakeGPS()
    main_module.RTC = FakeRTC
    main_module.run = _run

    with pytest.raises(StopLoop):
        main_module.main()

    gps, display, rtc = received["devices"]
    assert isinstance(gps, FakeGPS)
    assert isinstance(display, FakeDisplay)
    assert isinstance(rtc, FakeRTC)


def _run_until_stop(coro: object, clock: CountdownTime) -> None:
    """Drive a coroutine whose sleeps are paced by ``clock`` until it stops."""
    real_sleep = asyncio.sleep_ms

    async def _sleep(_ms: int) -> None:
        clock.sleep_ms(_ms)
        await real_sleep(0)

    asyncio.sleep_ms = _sleep
    try:
        with pytest.raises(StopLoop):
            asyncio.run(coro)
    finally:
        asyncio.sleep_ms = real_sleep


def _raise_os_error(**_kwargs: object) -> None:
    """Fail device construction the way a missing peripheral would."""
    raise OSError("no device")


def _raise_stop_loop(**_kwargs: object) -> None:
    """End an otherwise-infinite boot loop."""
    raise StopLoop


class _RecordingSync:
    """Synchronizer stub recording every consumed line."""

    def __init__(self) -> None:
        """Start with nothing consumed and no fix."""
        self.consumed: list = []
        self.synced = False

    def consume(self, line: str | None) -> None:
        """Record a non-empty line."""
        if line is not None:
            self.consumed.append(line)


class _RecordingEngine:
    """Engine stub recording transition targets and ending the sequence."""

    def __init__(self, stop_after: int = 4) -> None:
        """Land every transition immediately and stop after ``stop_after`` of them."""
        self.targets: list = []
        self.current_screen = clock_screens.WAIT_OFF
        self._stop_after = stop_after

    def begin_transition(
        self, target: int, *, effect: int | None = None, direction: int | None = None
    ) -> None:
        """Record the requested target screen."""
        self.targets.append(target)
        self.current_screen = target
        if len(self.targets) >= self._stop_after:
            raise StopLoop

    def advance_transition(self, _now: int) -> bool:
        """Land the transition on its first frame."""
        return True

    def reassert(self, _now: int) -> None:
        """Ignore reassert requests."""

    def show_frame_rate(self, _count: int, _elapsed: int, _now: int) -> None:
        """Ignore frame-rate samples."""


_BOARD = SimpleNamespace(
    uart=SimpleNamespace(bus_id=0, tx=0, rx=1),
    display=SimpleNamespace(
        spi_id=1,
        sck=26,
        mosi=27,
        cs=28,
        surface=SimpleNamespace(width_pixels=32, height_pixels=16, brightness=0.2),
    ),
)
