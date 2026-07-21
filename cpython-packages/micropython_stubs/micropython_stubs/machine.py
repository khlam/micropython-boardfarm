"""Host CPython stub of MicroPython's `machine` module."""

from __future__ import annotations

from collections.abc import Callable

# Mutable test state. Clear it between cases with reset().
pin_constructions: list[tuple] = []
_devices: dict[int, object] = {}
_uart_lines: list[bytes] = []
_pin_irqs: dict[object, Callable[[object], object] | None] = {}


def register_device(address: int, device: object) -> None:
    """Add a fake device responder at `address`."""
    _devices[address] = device


def feed_uart(lines: list[bytes]) -> None:
    """Queue byte lines for UART.readline() to return in order (FIFO)."""
    _uart_lines.extend(lines)


def fire_irq(pin_id: object) -> None:
    """Invoke the handler registered by Pin.irq() for `pin_id`, simulating an edge.

    Tests use this to drive interrupt-flag code paths on the host. Passes a
    lightweight object standing in for the triggering Pin, matching the
    single-argument handler signature MicroPython uses.
    """
    handler = _pin_irqs.get(pin_id)
    if handler is not None:
        handler(_IrqSource(pin_id))


def reset() -> None:
    """Clear recorded pin constructions, IRQ handlers, devices, and UART queue."""
    pin_constructions.clear()
    _devices.clear()
    _uart_lines.clear()
    _pin_irqs.clear()


class _IrqSource:
    """Stand-in for the Pin passed to an IRQ handler on the host."""

    def __init__(self, id: object) -> None:  # noqa: A002
        """Record the id of the pin that fired."""
        self.id = id


class Pin:
    """Fake `machine.Pin`. Records id + mode, supports value() get/set and irq()."""

    OUT = "OUT"
    IN = "IN"
    PULL_UP = "PULL_UP"
    IRQ_FALLING = 1
    IRQ_RISING = 2

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

    def irq(
        self,
        handler: Callable[[object], object] | None = None,
        trigger: object = None,  # noqa: ARG002
        **_kwargs: object,
    ) -> None:
        """Register `handler` for this pin so tests can fire it via fire_irq(id).

        `trigger` mirrors MicroPython's edge selector but is unused here: tests
        drive the handler explicitly via fire_irq(), so the edge is irrelevant.
        """
        _pin_irqs[self.id] = handler


class _I2CBase:
    """Common fake I2C / SoftI2C implementation."""

    def __init__(
        self,
        *args: object,
        sda: object = None,
        scl: object = None,
        freq: int = 100_000,
        **_kwargs: object,
    ) -> None:
        """Record bus id, pins, and frequency."""
        self.id = args[0] if args else None
        self.sda = sda
        self.scl = scl
        self.freq = freq

    def scan(self) -> list[int]:
        """Return registered device addresses in ascending order."""
        return sorted(_devices.keys())

    def readfrom_mem(self, addr: int, reg: int, nbytes: int, **_kwargs: object) -> bytes:
        """Read `nbytes` from `addr`/`reg`; raises OSError when unregistered.

        `addrsize` is accepted and ignored; the fake register file is keyed by
        `reg` as-is.
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

    def writeto(self, addr: int, buf: bytes | bytearray, **_kwargs: object) -> int:
        """Write one raw transaction and return its byte count."""
        dev = _devices.get(addr)
        if dev is None:
            raise OSError("ENODEV")
        data = bytes(buf)
        dev.write_raw(data)
        return len(data)

    def writevto(self, addr: int, vector: tuple, **_kwargs: object) -> int:
        """Write a vector as one raw transaction and return its byte count."""
        dev = _devices.get(addr)
        if dev is None:
            raise OSError("ENODEV")
        data = b"".join(bytes(part) for part in vector)
        dev.write_raw(data)
        return len(data)


class I2C(_I2CBase):
    """Fake `machine.I2C` (hardware peripheral)."""


class SoftI2C(_I2CBase):
    """Fake `machine.SoftI2C` (bit-banged)."""


class UART:
    """Fake `machine.UART` backed by a queued byte-line reader."""

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
