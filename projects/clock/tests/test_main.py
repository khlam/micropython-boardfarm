"""Host CPython tests for the clock firmware entry point and screen sequence.

main.py owns three things the other modules deliberately do not: the BOARD pin
table, the order screens step through, and the two recovery loops (init retry
and the guarded program restart).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from itertools import pairwise
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
    same_frame,
)

import clock_cycle
import clock_hardware
import clock_screens
import clock_transitions as ct
from clock_sync import ClockSynchronizer

_RMC_FIX = "$GPRMC,235958,A,3723.2475,N,12158.3416,W,0.0,0.0,230626,0.0,E*69"


@pytest.mark.parametrize(
    "main_module,wiring",
    [
        ("RP2040 with RP2040", ("RP2040-Zero", 0, 0, 1, 1, 26, 27, 28)),
        ("RP2350 with RP2350", ("RP2350", 1, 4, 5, 1, 10, 11, 9)),
        ("Generic ESP32S3 module with ESP32S3", ("ESP32-S3-Zero", 1, 13, 12, 1, 5, 6, 7)),
    ],
    indirect=["main_module"],
)
def test_board_table_selects_documented_wiring(main_module: object, wiring: tuple) -> None:
    # name, uart_id, tx, rx, spi_id, sck, mosi, cs
    assert tuple(main_module.BOARD) == wiring


def test_hardware_opens_devices_with_the_boards_pins() -> None:
    created: dict = {}

    def _display(**kwargs: object) -> FakeDisplay:
        created["display"] = dict(kwargs)
        return FakeDisplay()

    def _gps(**kwargs: object) -> FakeGPS:
        created["gps"] = dict(kwargs)
        return FakeGPS()

    hardware = clock_hardware.ClockHardware(_BOARD, _display, _gps, FakeRTC, brightness=0.2)
    devices = hardware.open()

    assert created["display"] == {
        "spi_id": 1,
        "sck": 26,
        "mosi": 27,
        "cs": 28,
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


@pytest.mark.parametrize("failing", ["_gps_cls", "_display_cls"], ids=["gps", "display"])
def test_a_failed_open_clears_the_stale_display_reference(failing: str) -> None:
    """A half-open retry must not flip a display from the previous attempt.

    Either device can be the one missing, and the display is constructed first,
    so a GPS failure leaves a live display object that must still be dropped.
    """
    hardware = clock_hardware.ClockHardware(
        _BOARD, lambda **_kw: FakeDisplay(), lambda **_kw: FakeGPS(), FakeRTC
    )
    hardware.open()

    setattr(hardware, failing, _raise_os_error)
    with pytest.raises(OSError):
        hardware.open()

    assert hardware.display is None
    hardware.flip_display()  # must not raise


def test_pump_gps_recovers_from_read_errors_and_idle_polls(
    main_module: object, status: object
) -> None:
    rtc = FakeRTC()
    sync = ClockSynchronizer(rtc)
    consumed: list = []
    sync_spy = SimpleNamespace(consume=lambda line: (consumed.append(line), sync.consume(line))[1])
    gps = FakeGPS([None, OSError("bus"), _RMC_FIX, None])
    clock = CountdownTime(stop_after=4)

    _run_until_stop(main_module.pump_gps(gps, sync_spy), clock)

    # The failed read is skipped, but every line either side of it still arrives
    # in order and the loop keeps polling afterwards.
    assert consumed == [None, _RMC_FIX, None]
    assert sync.synced is True
    assert rtc.value == (2026, 6, 23, 1, 15, 59, 58, 0)
    assert status.calls == ["read_err"]


def test_pump_gps_survives_an_rtc_that_rejects_the_write(
    main_module: object, status: object
) -> None:
    """A failing RTC raises out of `consume`; the pump must flag it, not die.

    `sync.consume` propagates OSError from the RTC, so this failure reaches the
    pump's guard from the opposite side to a GPS read error.
    """
    rtc = FakeRTC()
    sync = ClockSynchronizer(rtc)

    def _fail(_value: tuple) -> None:
        raise OSError("RTC unavailable")

    rtc.datetime = _fail
    gps = FakeGPS([_RMC_FIX, _RMC_FIX])
    clock = CountdownTime(stop_after=3)

    _run_until_stop(main_module.pump_gps(gps, sync), clock)

    assert sync.synced is False
    assert status.calls == ["read_err", "read_err"]


def test_clock_program_waits_for_a_fix_before_showing_a_clock_face(
    main_module: object,
) -> None:
    """Until GPS syncs, the sequence loops on the wait screen and shows no clock."""
    engine = _RecordingEngine(FakeRandom([0]))
    sync = SimpleNamespace(synced=False)

    with pytest.raises(StopLoop):
        asyncio.run(main_module.clock_program(engine, sync))

    assert clock_screens.WAIT_ON in engine.targets
    assert not (set(engine.targets) & set(clock_screens.REGULAR_SCREENS))


def test_clock_program_alternates_regular_faces_with_interstitials(
    main_module: object,
) -> None:
    engine = _RecordingEngine(FakeRandom([0, 1, 2]), stop_after=8)
    sync = SimpleNamespace(synced=True)

    with pytest.raises(StopLoop):
        asyncio.run(main_module.clock_program(engine, sync))

    assert engine.targets[0] == clock_screens.SCREEN_BRAND
    cycle = engine.targets[1:]
    kinds = [clock_screens.screen_spec(target).kind for target in cycle]
    assert kinds == [
        clock_screens.KIND_REGULAR,
        clock_screens.KIND_INTERSTITIAL,
        clock_screens.KIND_REGULAR,
        clock_screens.KIND_INTERSTITIAL,
        clock_screens.KIND_REGULAR,
        clock_screens.KIND_INTERSTITIAL,
        clock_screens.KIND_REGULAR,
    ]
    regulars = cycle[::2]
    assert all(left != right for left, right in pairwise(regulars))


def test_first_fix_during_wait_hold_reveals_clock_without_another_wait_animation(
    main_module: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _RecordingEngine(FakeRandom([0]), stop_after=3)
    sync = SimpleNamespace(synced=False)
    original_hold = main_module.hold_screen
    held: list = []

    async def _fix_during_wait(engine: object, *, stop: Callable[[], bool] | None = None) -> None:
        held.append(engine.current_screen)
        if engine.current_screen == clock_screens.WAIT_ON:
            assert stop is not None
            assert stop() is False
            sync.synced = True
            assert stop() is True
        await original_hold(engine, stop=stop)

    monkeypatch.setattr(main_module, "hold_screen", _fix_during_wait)

    with pytest.raises(StopLoop):
        asyncio.run(main_module.clock_program(engine, sync))

    assert engine.targets[:2] == [clock_screens.SCREEN_BRAND, clock_screens.WAIT_ON]
    assert engine.targets[2] in clock_screens.REGULAR_SCREENS
    assert held == [clock_screens.WAIT_ON]


def test_whole_sequence_runs_against_the_real_engine_and_renderers(
    main_module: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One pass with nothing faked below `clock_program` but the hardware itself.

    Every other sequence test drives `_RecordingEngine`, which lands transitions
    on their first frame and ignores reasserts — so the real engine, the screen
    renderers and the transition effects are never exercised together. This runs
    the actual composition and checks the display ends up holding the frame the
    screen table says it should.
    """
    display = FakeDisplay()
    rtc = FakeRTC((2026, 6, 23, 1, 12, 30, 0, 0))
    clock = AdvancingTime()
    sync = SimpleNamespace(synced=True, boot_time=(2026, 6, 23, 1, 12, 0, 0))
    engine = clock_cycle.DisplayEngine(display, rtc, clock=clock, rng=FakeRandom([0]), sync=sync)

    real_sleep = asyncio.sleep_ms

    async def _advancing_sleep(ms: int) -> None:
        clock.advance(max(1, ms))
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep_ms", _advancing_sleep)
    # Hops are brand -> regular -> interstitial; stop before the fourth so the
    # sequence is parked on the interstitial it just landed.
    hops = {"n": 0}
    original = engine.begin_transition

    def _counted(target: int, **kwargs: object) -> None:
        hops["n"] += 1
        if hops["n"] > 3:
            raise StopLoop
        original(target, **kwargs)

    engine.begin_transition = _counted

    with pytest.raises(StopLoop):
        asyncio.run(main_module.clock_program(engine, sync))

    assert engine.current_screen in clock_screens.INTERSTITIAL_SCREENS
    # The landed screen is really rendered, not a stub frame.
    parts = engine._parts_for_screen(engine.current_screen)
    assert same_frame(display.shown[-1], clock_screens.render_screen(engine.current_screen, parts))
    # Real transitions animate, so far more frames were pushed than screens visited.
    assert len(display.shown) > 3 * ct.TRANSITION_STEPS


def test_guarded_program_restarts_the_sequence_after_a_render_error(
    main_module: object, status: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A render glitch must heal the LED and restart, never stop the clock."""
    attempts = {"n": 0}

    async def _failing(*_args: object) -> None:
        attempts["n"] += 1
        if attempts["n"] >= 3:
            raise StopLoop
        raise ValueError("render glitch")

    main_module.clock_program = _failing
    sleeps: list = []

    async def _sleep(ms: int) -> None:
        sleeps.append(ms)

    monkeypatch.setattr(asyncio, "sleep_ms", _sleep)

    with pytest.raises(StopLoop):
        asyncio.run(
            main_module.guarded_program(
                _RecordingEngine(FakeRandom([0])), SimpleNamespace(synced=True)
            ),
        )

    assert attempts["n"] == 3
    assert status.calls == ["read_err", "streaming", "read_err", "streaming"]
    assert sleeps == [200, 200]


def test_main_retries_after_an_init_failure(
    main_module: object, status: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing GPS at boot flashes the init LED and retries rather than halting."""
    attempts = {"n": 0}

    def _gps(**_kwargs: object) -> FakeGPS:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("no gps")
        return FakeGPS()

    main_module.MAX7219 = lambda **_kw: FakeDisplay()
    main_module.GPS = _gps
    main_module.RTC = FakeRTC
    main_module.run = lambda *_args: _raise_stop_loop()
    sleeps: list = []
    monkeypatch.setattr(main_module.time, "sleep_ms", sleeps.append)

    with pytest.raises(StopLoop):
        main_module.main()

    assert attempts["n"] == 2
    assert status.calls == ["boot", "i2c_init", "init_err", "boot", "i2c_init"]
    assert sleeps == [300, 1_000]


def test_main_hands_devices_to_runtime_and_button_flips_the_live_display(
    main_module: object,
) -> None:
    received: dict = {}
    registered: list = []
    main_module.button.on_press = registered.append

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
    assert len(registered) == 1
    registered[0]()
    assert display.flips == 1


def test_run_starts_the_event_loop_with_the_devices_in_order(
    main_module: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run` is the only untested hop between `main` and the async runtime.

    It is one line, but a swapped `gps`/`display` argument would ship green:
    `main` hands it three objects positionally and nothing else checks them.
    """
    received: list = []

    async def _run_async(gps: object, display: object, rtc: object) -> None:
        received.append((gps, display, rtc))

    monkeypatch.setattr(main_module, "run_async", _run_async)
    gps, display, rtc = FakeGPS(), FakeDisplay(), FakeRTC()

    main_module.run(gps, display, rtc)

    assert received == [(gps, display, rtc)]


def test_main_reopens_the_hardware_if_the_runtime_ever_returns(
    main_module: object, status: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stopped event loop must re-open the buses, not fall out of `main`.

    `run` returns only if the loop stops; the boot loop then has to go round
    again. Every other test raises out of `run`, so nothing exercises the
    ordinary return path.
    """
    opens = {"n": 0}

    def _display(**_kwargs: object) -> FakeDisplay:
        opens["n"] += 1
        return FakeDisplay()

    main_module.MAX7219 = _display
    main_module.GPS = lambda **_kw: FakeGPS()
    main_module.RTC = FakeRTC
    main_module.run = lambda *_args: _raise_stop_loop() if opens["n"] >= 2 else None
    monkeypatch.setattr(main_module.time, "sleep_ms", lambda _ms: None)

    with pytest.raises(StopLoop):
        main_module.main()

    assert opens["n"] == 2
    # A clean return is not an error, so the LED never shows the init fault.
    assert status.calls == ["boot", "i2c_init", "i2c_init"]


def test_runtime_keeps_gps_pumping_while_display_waits(
    main_module: object, monkeypatch: pytest.MonkeyPatch, status: object
) -> None:
    rtc = FakeRTC()
    display = FakeDisplay()
    gps = FakeGPS([None, _RMC_FIX])
    display_finished: list = []

    async def _display_program(engine: object, sync: object) -> None:
        assert sync.synced is False
        assert engine._display is display
        assert engine._rtc is rtc
        # A bounded number of scheduler yields catches sequential startup without hanging.
        for _ in range(5):
            await asyncio.sleep(0)
            if sync.synced:
                break
        assert sync.synced is True
        assert engine._sync is sync
        assert rtc.value == (2026, 6, 23, 1, 15, 59, 58, 0)
        display_finished.append(True)

    async def _scenario() -> None:
        runtime = asyncio.create_task(main_module.run_async(gps, display, rtc))
        for _ in range(10):
            await asyncio.sleep(0)
            if runtime.done():
                # Propagate failures in the display task before cancellation.
                await runtime
        runtime.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runtime

    monkeypatch.setattr(main_module, "guarded_program", _display_program)
    asyncio.run(_scenario())

    assert status.calls == ["streaming"]
    assert display_finished == [True]
    assert rtc.value == (2026, 6, 23, 1, 15, 59, 58, 0)


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


class _RecordingEngine:
    """Engine stub recording transition targets and ending the sequence."""

    def __init__(self, rng: object, stop_after: int = 4) -> None:
        """Land every transition immediately and stop after ``stop_after`` of them."""
        self.targets: list = []
        self.current_screen = clock_screens.WAIT_OFF
        self.clock = AdvancingTime()
        self.rng = rng
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


_BOARD = SimpleNamespace(uart_id=0, tx=0, rx=1, spi_id=1, sck=26, mosi=27, cs=28)
