"""Host CPython stub of the `machine` module used by host pytest.

Records Pin construction and routes I2C / SoftI2C reads + writes to fake
devices registered at the matching address. Union of the per-package stubs
previously kept under each `packages/<pkg>/stubs/` directory — exactly one
copy now lives here so every test in the session sees the same module.

Test state (`pin_constructions`, `_devices`) is module-level; tests reset
it between cases by calling `reset()` from an autouse fixture.
"""

from __future__ import annotations

# Test state. Cleared by tests' autouse fixtures via reset().
pin_constructions: list[tuple] = []
_devices: dict[int, object] = {}
_uart_lines: list[bytes] = []


def register_device(address: int, device: object) -> None:
    """Add a fake device responder at `address`."""
    _devices[address] = device


def feed_uart(lines: list[bytes]) -> None:
    """Queue byte lines for UART.readline() to return in order (FIFO)."""
    _uart_lines.extend(lines)


def reset() -> None:
    """Clear recorded pin constructions, the device registry, and UART queue."""
    pin_constructions.clear()
    _devices.clear()
    _uart_lines.clear()


class Pin:
    """Fake `machine.Pin`. Records id + mode, supports value() get/set."""

    OUT = "OUT"

    def __init__(
        self,
        id: int | str,  # noqa: A002
        mode: str | None = None,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        """Record the pin id and mode for later inspection."""
        self.id = id
        self.mode = mode
        self._value = 0
        pin_constructions.append((id, mode))

    def value(self, v: int | None = None) -> int | None:
        """Get or set the pin value (0/1)."""
        if v is None:
            return self._value
        self._value = int(bool(v))
        return None


class _I2CBase:
    """Common fake I2C / SoftI2C — records bus id (positional) + sda/scl + freq.

    `I2C(0, sda=..., scl=...)` (hardware peripheral style, used by i2c_bus)
    and `I2C(sda=..., scl=...)` (kwarg-only style, used by other packages)
    both work.
    """

    def __init__(
        self,
        *args: object,
        sda: object = None,
        scl: object = None,
        freq: int = 100_000,
        **_kwargs: object,
    ) -> None:
        """Record positional bus id (if any) and sda/scl/freq."""
        self.id = args[0] if args else None
        self.sda = sda
        self.scl = scl
        self.freq = freq

    def scan(self) -> list[int]:
        """Return registered device addresses in ascending order."""
        return sorted(_devices.keys())

    def readfrom_mem(self, addr: int, reg: int, nbytes: int, **_kwargs: object) -> bytes:
        """Read `nbytes` from `addr`/`reg`; raises OSError when unregistered.

        `addrsize` (16-bit register addressing, used by the VL53L5CX driver) is
        accepted and ignored — the fake register file is keyed by `reg` as-is.
        """
        dev = _devices.get(addr)
        if dev is None:
            raise OSError("ENODEV")
        return dev.read(reg, nbytes)

    def readfrom_mem_into(self, addr: int, reg: int, buf: bytearray, **_kwargs: object) -> None:
        """Read `len(buf)` from `addr`/`reg` into `buf` in place."""
        dev = _devices.get(addr)
        if dev is None:
            raise OSError("ENODEV")
        data = dev.read(reg, len(buf))
        for i, b in enumerate(data):
            buf[i] = b

    def writeto_mem(self, addr: int, reg: int, buf: bytes, **_kwargs: object) -> None:
        """Write `buf` to `addr`/`reg`; raises OSError when unregistered."""
        dev = _devices.get(addr)
        if dev is None:
            raise OSError("ENODEV")
        dev.write(reg, bytes(buf))


class I2C(_I2CBase):
    """Fake `machine.I2C` (hardware peripheral)."""


class SoftI2C(_I2CBase):
    """Fake `machine.SoftI2C` (bit-banged)."""


class UART:
    """Fake `machine.UART` — records the peripheral id + tx/rx pins + baudrate.

    `readline()` pops from the module-level queue seeded by `feed_uart()`, so
    tests can script NMEA bytes for a driver that opens its own UART; it returns
    None once the queue drains (mirroring a timeout on a quiet line).
    """

    def __init__(
        self,
        id: int | None = None,  # noqa: A002
        *_args: object,
        baudrate: int = 9600,
        tx: object = None,
        rx: object = None,
        timeout: int = 0,
        **_kwargs: object,
    ) -> None:
        """Record the positional bus id and the tx/rx/baudrate/timeout kwargs."""
        self.id = id
        self.baudrate = baudrate
        self.tx = tx
        self.rx = rx
        self.timeout = timeout

    def readline(self) -> bytes | None:
        """Return the next queued byte line, or None when the queue is empty."""
        return _uart_lines.pop(0) if _uart_lines else None
