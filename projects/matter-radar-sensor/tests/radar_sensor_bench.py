"""A virtual bench that runs the sensor firmware's real main() on the host.

Only the boundary is fake: the clock, the radar wired to UART1, and the Matter
controller behind ``matter_native``. The firmware's own code runs unchanged.

Time is virtual. It moves only when every firmware loop is waiting, and then
jumps straight to the next thing that happens, so the radar's two-second probe
and half-second report timeouts cost nothing. At each instant the bench first
delivers the inputs due then, then the radar's report, and only then lets the
firmware run.

The radar sends one report on every 100 ms mark (0, 100, 200, ...), the rate
HLK-LD2450 serial protocol V1.03 section 2.3 specifies, to whichever UART is
open at its baud rate. An HLK-LD2420 also answers each command it receives with
a success ACK, as its serial command protocol describes.
"""

import asyncio
import selectors
from collections import namedtuple
from collections.abc import Callable

import machine
import matter_native

from micropython_stubs.testing import StopLoopError

# One target the radar tracks, in the units its reports carry.
Seen = namedtuple("Seen", ("x_mm", "y_mm", "speed_cm_s", "resolution_mm"))
# The hold light setting ESP-Matter restores from flash at boot.
StoredHoldLight = namedtuple("StoredHoldLight", ("on", "level"))

# Inputs. Each takes effect at ``at_ms`` on the virtual clock.
# From at_ms the radar reports these targets, one per tracking slot; () is an empty room.
Scene = namedtuple("Scene", ("at_ms", "targets"))
# From at_ms the radar sends nothing, as when its TX wire comes loose.
Silent = namedtuple("Silent", ("at_ms",))
# At at_ms the UART read raises OSError(message). Pick a time between reports.
UartFault = namedtuple("UartFault", ("at_ms", "message"))
# A controller writes the hold light's on/off and level (0-254).
HoldLight = namedtuple("HoldLight", ("at_ms", "on", "level"))
# The next Matter poll after at_ms fails with EIO.
PollFault = namedtuple("PollFault", ("at_ms",))
# The next occupancy publish to ESP-Matter after at_ms fails with EIO.
PublishFault = namedtuple("PublishFault", ("at_ms",))
# A commissioner's pairing attempt fails.
PairingFails = namedtuple("PairingFails", ("at_ms",))
# A commissioning window opens.
WindowOpens = namedtuple("WindowOpens", ("at_ms",))
# The Wi-Fi link comes up. The bench sends it at boot for an online board.
_NetworkUp = namedtuple("_NetworkUp", ("at_ms",))

# Matter specification identifiers: endpoint IDs follow creation order.
OCCUPANCY_ENDPOINT = 1
HOLD_LIGHT_ENDPOINT = 2
OCCUPANCY = (0x0406, 0x0000)  # Occupancy Sensing cluster, Occupancy attribute
ON_OFF = (0x0006, 0x0000)  # On/Off cluster, OnOff attribute
LEVEL = (0x0008, 0x0000)  # Level Control cluster, CurrentLevel attribute

# matter_native record values (firmware-packages/matter/native/include/bridge.h).
_SESSION_FAILED = 2
_WINDOW_OPENED = 3
_NETWORK_CONNECTED = 1
_NETWORK_DISCONNECTED = 0

_REPORT_INTERVAL_MS = 100

# HLK-LD2450 serial protocol V1.03 sections 1.1 and 2.3.
_LD2450_BAUD = 256_000
_LD2450_HEADER = b"\xaa\xff\x03\x00"
_LD2450_FOOTER = b"\x55\xcc"
_LD2450_SLOTS = 3
# HLK-LD2420 serial command protocol: reports in energy mode, command ACKs.
_LD2420_BAUD = 115_200
_LD2420_HEADER = b"\xf4\xf3\xf2\xf1"
_LD2420_FOOTER = b"\xf8\xf7\xf6\xf5"
_LD2420_GATES = 16
_LD2420_COMMAND_HEADER = b"\xfd\xfc\xfb\xfa"
_LD2420_COMMAND_FOOTER = b"\x04\x03\x02\x01"
_LD2420_COMMAND_AT = 6
_LD2420_ACK_FLAG = 0x0100


class Bench:
    """The clock, the radar, and the Matter controller around one firmware run."""

    def __init__(self, *, radar: str | None, online: bool, inputs: tuple, until_ms: int) -> None:
        """Set up the surroundings before the firmware boots.

        Args:
            radar: ``"LD2450"``, ``"LD2420"``, or None for no radar wired.
            online: Whether the Wi-Fi link comes up at boot.
            inputs: Input values, delivered in ``at_ms`` order.
            until_ms: Last instant the firmware runs before the bench stops it.
        """
        self.now_ms = 0
        self.published = []
        self._radar = radar
        self._online = online
        self._until_ms = until_ms
        self._scene = None
        self._next_report_ms = 0
        self._answered = {}
        boot = (_NetworkUp(0),) if online else ()
        self._inputs = sorted((*boot, *inputs), key=lambda item: item.at_ms)

    def ticks_ms(self) -> int:
        """Return the virtual time, as ``time.ticks_ms()`` does on the board."""
        return self.now_ms

    @staticmethod
    async def sleep_ms(delay_ms: int) -> None:
        """Sleep on the virtual clock, as ``asyncio.sleep_ms()`` does on the board."""
        await asyncio.sleep(delay_ms / 1000)

    def new_loop(self) -> asyncio.AbstractEventLoop:
        """Return an event loop whose clock is this bench's.

        Returns:
            The loop ``asyncio.run()`` drives the firmware on.
        """
        return _VirtualLoop(self)

    def attributes_publish(
        self, publish: Callable[[int, tuple], None], endpoint_id: int, updates: tuple
    ) -> None:
        """Publish through the fake stack, recording each occupancy it accepts.

        Args:
            publish: The fake stack's own ``attributes_publish``.
            endpoint_id: The endpoint being published.
            updates: ``(cluster, attribute, value)`` triples.
        """
        publish(endpoint_id, updates)
        for cluster, attribute, value in updates:
            if (endpoint_id, (cluster, attribute)) == (OCCUPANCY_ENDPOINT, OCCUPANCY):
                self.published.append((self.now_ms, value))

    def advance(self, timeout_s: float | None) -> None:
        """Deliver what is due now, or move the clock to the next event.

        The event loop calls this where a real loop would block on I/O.

        Args:
            timeout_s: How long the loop would wait for its next timer, or None
                when it has no timer.

        Raises:
            StopLoopError: The next event comes after ``until_ms``.
        """
        if self._deliver():
            return
        next_ms = self._inputs[0].at_ms if self._inputs else self._next_report_ms
        next_ms = min(next_ms, self._next_report_ms)
        if timeout_s is not None:
            next_ms = min(next_ms, self.now_ms + round(timeout_s * 1000))
        if next_ms > self._until_ms:
            raise StopLoopError
        self.now_ms = next_ms
        self._deliver()

    def _deliver(self) -> bool:
        """Apply the inputs due now, send the radar's report, and answer commands.

        Returns:
            Whether anything reached the firmware.
        """
        delivered = False
        while self._inputs and self._inputs[0].at_ms <= self.now_ms:
            _APPLY[type(self._inputs[0])](self, self._inputs.pop(0))
            delivered = True
        if self._next_report_ms <= self.now_ms:
            self._next_report_ms += _REPORT_INTERVAL_MS
            delivered = self._send_report() or delivered
        return self._answer_commands() or delivered

    def _send_report(self) -> bool:
        """Send one report of the current scene, if the radar is talking.

        Returns:
            Whether a report went out.
        """
        uart = self._open_uart()
        if uart is None or self._scene is None:
            return False
        encode = _ld2450_report if self._radar == "LD2450" else _ld2420_report
        machine.feed_uart_bytes(encode(self._scene))
        return True

    def _answer_commands(self) -> bool:
        """Answer every command an LD2420 has not answered yet with a success ACK.

        Returns:
            Whether any ACK went out.
        """
        uart = self._open_uart()
        if uart is None or self._radar != "LD2420":
            return False
        answered = self._answered.get(uart, 0)
        for frame in uart.writes[answered:]:
            command = int.from_bytes(frame[_LD2420_COMMAND_AT : _LD2420_COMMAND_AT + 2], "little")
            machine.feed_uart_bytes(_ld2420_ack(command))
        self._answered[uart] = len(uart.writes)
        return len(uart.writes) > answered

    def _open_uart(self) -> object | None:
        """Return the open UART at the radar's baud rate, if there is one."""
        baud = {"LD2450": _LD2450_BAUD, "LD2420": _LD2420_BAUD}.get(self._radar)
        for uart in machine.uart_constructions:
            if not uart.deinitialized and uart.baudrate == baud:
                return uart
        return None

    def _apply_scene(self, scene: Scene) -> None:
        self._scene = tuple(scene.targets)

    def _apply_silent(self, _silent: Silent) -> None:
        self._scene = None

    def _apply_uart_fault(self, fault: UartFault) -> None:
        # The empty feed wakes a waiting reader so its next read raises now.
        machine.fail_uart_reads(OSError(fault.message))
        machine.feed_uart_bytes(b"")

    def _apply_hold_light(self, write: HoldLight) -> None:
        matter_native.inject_remote_write(HOLD_LIGHT_ENDPOINT, *ON_OFF, write.on)
        matter_native.inject_remote_write(HOLD_LIGHT_ENDPOINT, *LEVEL, write.level)

    def _apply_poll_fault(self, _fault: PollFault) -> None:
        # A poll fetches a snapshot only after something changed, so restate
        # the network link to give it something to fetch.
        matter_native.fail_next("snapshot")
        link = _NETWORK_CONNECTED if self._online else _NETWORK_DISCONNECTED
        matter_native.inject_network_event(link)

    def _apply_publish_fault(self, _fault: PublishFault) -> None:
        matter_native.fail_next("attributes_publish")

    def _apply_pairing_fails(self, _attempt: PairingFails) -> None:
        matter_native.inject_commissioning_event(_SESSION_FAILED)

    def _apply_window_opens(self, _window: WindowOpens) -> None:
        matter_native.inject_commissioning_event(_WINDOW_OPENED)

    def _apply_network_up(self, _link: _NetworkUp) -> None:
        matter_native.inject_network_event(_NETWORK_CONNECTED)


_APPLY = {
    Scene: Bench._apply_scene,
    Silent: Bench._apply_silent,
    UartFault: Bench._apply_uart_fault,
    HoldLight: Bench._apply_hold_light,
    PollFault: Bench._apply_poll_fault,
    PublishFault: Bench._apply_publish_fault,
    PairingFails: Bench._apply_pairing_fails,
    WindowOpens: Bench._apply_window_opens,
    _NetworkUp: Bench._apply_network_up,
}


def stored_attributes(hold_light: StoredHoldLight | None) -> dict:
    """Return what ESP-Matter holds in flash for the hold light before boot.

    Args:
        hold_light: The stored setting, or None for a board never configured.

    Returns:
        ``(endpoint, cluster, attribute)`` to value, as ``matter_native.reset()`` takes.
    """
    if hold_light is None:
        return {}
    return {
        (HOLD_LIGHT_ENDPOINT, *ON_OFF): hold_light.on,
        (HOLD_LIGHT_ENDPOINT, *LEVEL): hold_light.level,
    }


class _VirtualSelector(selectors.SelectSelector):
    """Never block; hand the wait to the bench instead."""

    def __init__(self, bench: Bench) -> None:
        super().__init__()
        self._bench = bench

    def select(self, timeout: float | None = None) -> list:
        self._bench.advance(timeout)
        return []


class _VirtualLoop(asyncio.SelectorEventLoop):
    """An asyncio loop that reads the bench's clock."""

    def __init__(self, bench: Bench) -> None:
        self._bench = bench
        super().__init__(_VirtualSelector(bench))

    def time(self) -> float:
        return self._bench.now_ms / 1000


def _ld2450_report(targets: tuple) -> bytes:
    """Encode one 30-byte LD2450 report; empty slots are all zero."""
    body = b""
    for slot in range(_LD2450_SLOTS):
        if slot >= len(targets):
            body += bytes(8)
            continue
        seen = targets[slot]
        for value in (seen.x_mm, seen.y_mm, seen.speed_cm_s):
            # Sign-magnitude, with the top bit set for a positive value.
            body += (-value if value < 0 else value | 0x8000).to_bytes(2, "little")
        body += seen.resolution_mm.to_bytes(2, "little")
    return _LD2450_HEADER + body + _LD2450_FOOTER


def _ld2420_report(targets: tuple) -> bytes:
    """Encode one 45-byte LD2420 energy-mode report from the first target's range."""
    present = bool(targets)
    distance_cm = targets[0].y_mm // 10 if present else 0
    body = bytes((int(present),)) + distance_cm.to_bytes(2, "little") + bytes(2 * _LD2420_GATES)
    return _LD2420_HEADER + len(body).to_bytes(2, "little") + body + _LD2420_FOOTER


def _ld2420_ack(command: int) -> bytes:
    """Encode the LD2420's success ACK for one command word."""
    body = (command | _LD2420_ACK_FLAG).to_bytes(2, "little") + bytes(2)
    return _LD2420_COMMAND_HEADER + len(body).to_bytes(2, "little") + body + _LD2420_COMMAND_FOOTER
