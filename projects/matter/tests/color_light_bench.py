"""A virtual bench that runs the colour light firmware's whole main.py on the host.

Only the boundary is fake: the clock and the Matter controller behind
``matter_native``. The firmware's own code runs unchanged, through to the poll
loop its last line starts.

Time is virtual and moves only when the firmware sleeps. Each sleep jumps the
clock forward and delivers every input due by then, so the firmware's next poll
sees it. Inputs due at boot reach the stack while ``node.start()`` brings it up,
as on the board. The bench stops the firmware at the first sleep that would pass
``until_ms``.
"""

from collections import namedtuple
from collections.abc import Callable

import matter_native

from micropython_stubs.testing import StopLoopError

# The colour ESP-Matter restores from flash for the light at boot, in hue and
# saturation mode. Each value is 0-254, as a controller writes it.
StoredLight = namedtuple("StoredLight", ("on", "level", "hue", "saturation"))

# Inputs. Each takes effect at ``at_ms`` on the virtual clock.
# A commissioning window opens, or closes.
WindowOpens = namedtuple("WindowOpens", ("at_ms",))
WindowCloses = namedtuple("WindowCloses", ("at_ms",))
# A commissioner starts pairing, completes it (a fabric is committed, then the
# session completes), or the attempt fails.
PairingStarts = namedtuple("PairingStarts", ("at_ms",))
PairingCompletes = namedtuple("PairingCompletes", ("at_ms",))
PairingFails = namedtuple("PairingFails", ("at_ms",))
# The Wi-Fi link comes up, or drops. The bench sends WifiUp at boot for an
# online board.
WifiUp = namedtuple("WifiUp", ("at_ms",))
WifiDown = namedtuple("WifiDown", ("at_ms",))
# A controller sets the light in hue and saturation mode; each value is 0-254.
LightSet = namedtuple("LightSet", ("at_ms", "on", "level", "hue", "saturation"))
# A controller writes only the light's level, which may be outside 0-254.
LevelWrite = namedtuple("LevelWrite", ("at_ms", "level"))
# Apple Home removes the light: the last fabric goes, and the bridge reopens
# the commissioning window, as callbacks.cpp does.
LightRemoved = namedtuple("LightRemoved", ("at_ms",))
# The next Matter poll after at_ms fails with EIO.
PollFault = namedtuple("PollFault", ("at_ms",))

# Matter specification identifiers. The light is the node's only endpoint.
LIGHT_ENDPOINT = 1
_ATTRIBUTE_NAMES = {
    (0x0006, 0x0000): "on",  # On/Off cluster, OnOff
    (0x0008, 0x0000): "level",  # Level Control cluster, CurrentLevel
    (0x0300, 0x0000): "hue",  # Color Control cluster, CurrentHue
    (0x0300, 0x0001): "saturation",  # Color Control cluster, CurrentSaturation
    (0x0300, 0x0008): "color_mode",  # Color Control cluster, ColorMode
    (0x0300, 0x4001): "enhanced_color_mode",  # Color Control cluster, EnhancedColorMode
}
_PATHS = {name: path for path, name in _ATTRIBUTE_NAMES.items()}
_HUE_SATURATION_MODE = 0

# The one fabric a paired board restores: index, fabric, node, vendor, label.
FABRIC = (1, 0x1234, 0x5678, 0xFFF1, "controller")

# matter_native record values (firmware-packages/matter/native/include/matter/bridge.h).
_SESSION_STARTED = 0
_SESSION_COMPLETE = 1
_SESSION_FAILED = 2
_WINDOW_OPENED = 3
_WINDOW_CLOSED = 4
_NETWORK_DISCONNECTED = 0
_NETWORK_CONNECTED = 1

_TICKS_PERIOD = 1 << 30
_HALF_TICKS_PERIOD = 1 << 29


class Bench:
    """The clock and the Matter controller around one firmware run."""

    def __init__(self, *, online: bool, inputs: tuple, until_ms: int) -> None:
        """Set up the surroundings before the firmware boots.

        Args:
            online: Whether the Wi-Fi link comes up at boot.
            inputs: Input values, delivered in ``at_ms`` order.
            until_ms: Last instant the firmware runs before the bench stops it.
        """
        self.now_ms = 0
        self.published = []
        self._online = online
        self._until_ms = until_ms
        boot = (WifiUp(0),) if online else ()
        self._inputs = sorted((*boot, *inputs), key=lambda item: item.at_ms)

    def ticks_ms(self) -> int:
        """Return the virtual time, as ``time.ticks_ms()`` does on the board."""
        return self.now_ms

    @staticmethod
    def ticks_diff(newer: int, older: int) -> int:
        """Return MicroPython's signed, wrap-safe tick difference."""
        return (newer - older + _HALF_TICKS_PERIOD) % _TICKS_PERIOD - _HALF_TICKS_PERIOD

    def sleep_ms(self, delay_ms: int) -> None:
        """Move the clock forward and deliver the inputs due by then.

        Args:
            delay_ms: How long the firmware sleeps.

        Raises:
            StopLoopError: The sleep would end after ``until_ms``.
        """
        if self.now_ms + delay_ms > self._until_ms:
            raise StopLoopError
        self.now_ms += delay_ms
        self._deliver()

    def start(self, start: Callable[[], None]) -> None:
        """Start the fake stack, then deliver the inputs due at boot.

        Args:
            start: The fake stack's own ``start``.
        """
        start()
        self._deliver()

    def attributes_publish(
        self, publish: Callable[[int, tuple], None], endpoint_id: int, updates: tuple
    ) -> None:
        """Publish through the fake stack, recording each batch it accepts by name.

        Args:
            publish: The fake stack's own ``attributes_publish``.
            endpoint_id: The endpoint being published.
            updates: ``(cluster, attribute, value)`` triples.
        """
        publish(endpoint_id, updates)
        self.published.append(
            {_ATTRIBUTE_NAMES[(cluster, attribute)]: value for cluster, attribute, value in updates}
        )

    def _deliver(self) -> None:
        """Apply every input due now."""
        while self._inputs and self._inputs[0].at_ms <= self.now_ms:
            _APPLY[type(self._inputs[0])](self, self._inputs.pop(0))

    def _apply_window_opens(self, _window: WindowOpens) -> None:
        matter_native.inject_commissioning_event(_WINDOW_OPENED)

    def _apply_window_closes(self, _window: WindowCloses) -> None:
        matter_native.inject_commissioning_event(_WINDOW_CLOSED)

    def _apply_pairing_starts(self, _attempt: PairingStarts) -> None:
        matter_native.inject_commissioning_event(_SESSION_STARTED)

    def _apply_pairing_completes(self, _attempt: PairingCompletes) -> None:
        matter_native.seed_fabrics([FABRIC])
        matter_native.inject_fabric_count()
        matter_native.inject_commissioning_event(_SESSION_COMPLETE)

    def _apply_pairing_fails(self, _attempt: PairingFails) -> None:
        matter_native.inject_commissioning_event(_SESSION_FAILED)

    def _apply_wifi_up(self, _link: WifiUp) -> None:
        self._online = True
        matter_native.inject_network_event(_NETWORK_CONNECTED)

    def _apply_wifi_down(self, _link: WifiDown) -> None:
        self._online = False
        matter_native.inject_network_event(_NETWORK_DISCONNECTED)

    def _apply_light_set(self, write: LightSet) -> None:
        for name, value in (
            ("on", write.on),
            ("level", write.level),
            ("hue", write.hue),
            ("saturation", write.saturation),
            ("color_mode", _HUE_SATURATION_MODE),
            ("enhanced_color_mode", _HUE_SATURATION_MODE),
        ):
            matter_native.inject_remote_write(LIGHT_ENDPOINT, *_PATHS[name], value)

    def _apply_level_write(self, write: LevelWrite) -> None:
        matter_native.inject_remote_write(LIGHT_ENDPOINT, *_PATHS["level"], write.level)

    def _apply_light_removed(self, _removal: LightRemoved) -> None:
        matter_native.seed_fabrics([])
        matter_native.inject_fabric_count()
        matter_native.inject_commissioning_event(_WINDOW_OPENED)

    def _apply_poll_fault(self, _fault: PollFault) -> None:
        # A poll fetches a snapshot only after something changed, so restate
        # the network link to give it something to fetch.
        matter_native.fail_next("snapshot")
        link = _NETWORK_CONNECTED if self._online else _NETWORK_DISCONNECTED
        matter_native.inject_network_event(link)


_APPLY = {
    WindowOpens: Bench._apply_window_opens,
    WindowCloses: Bench._apply_window_closes,
    PairingStarts: Bench._apply_pairing_starts,
    PairingCompletes: Bench._apply_pairing_completes,
    PairingFails: Bench._apply_pairing_fails,
    WifiUp: Bench._apply_wifi_up,
    WifiDown: Bench._apply_wifi_down,
    LightSet: Bench._apply_light_set,
    LevelWrite: Bench._apply_level_write,
    LightRemoved: Bench._apply_light_removed,
    PollFault: Bench._apply_poll_fault,
}


def stored_attributes(light: StoredLight | None) -> dict:
    """Return what ESP-Matter holds in flash for the light before boot.

    Args:
        light: The stored colour, or None for a light never set.

    Returns:
        ``(endpoint, cluster, attribute)`` to value, as ``matter_native.reset()`` takes.
    """
    if light is None:
        return {}
    values = {
        "on": light.on,
        "level": light.level,
        "hue": light.hue,
        "saturation": light.saturation,
        "color_mode": _HUE_SATURATION_MODE,
        "enhanced_color_mode": _HUE_SATURATION_MODE,
    }
    return {(LIGHT_ENDPOINT, *_PATHS[name]): value for name, value in values.items()}
