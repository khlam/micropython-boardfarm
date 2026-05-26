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


def register_device(address: int, device: object) -> None:
    """Add a fake device responder at `address`."""
    _devices[address] = device


def reset() -> None:
    """Clear recorded pin constructions and the device registry."""
    pin_constructions.clear()
    _devices.clear()


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

    def readfrom_mem(self, addr: int, reg: int, nbytes: int) -> bytes:
        """Read `nbytes` from `addr`/`reg`; raises OSError when unregistered."""
        dev = _devices.get(addr)
        if dev is None:
            raise OSError("ENODEV")
        return dev.read(reg, nbytes)

    def readfrom_mem_into(self, addr: int, reg: int, buf: bytearray) -> None:
        """Read `len(buf)` from `addr`/`reg` into `buf` in place."""
        dev = _devices.get(addr)
        if dev is None:
            raise OSError("ENODEV")
        data = dev.read(reg, len(buf))
        for i, b in enumerate(data):
            buf[i] = b

    def writeto_mem(self, addr: int, reg: int, buf: bytes) -> None:
        """Write `buf` to `addr`/`reg`; raises OSError when unregistered."""
        dev = _devices.get(addr)
        if dev is None:
            raise OSError("ENODEV")
        dev.write(reg, bytes(buf))


class I2C(_I2CBase):
    """Fake `machine.I2C` (hardware peripheral)."""


class SoftI2C(_I2CBase):
    """Fake `machine.SoftI2C` (bit-banged)."""
