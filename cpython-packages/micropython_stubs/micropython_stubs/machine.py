"""Host CPython stub of MicroPython's `machine` module."""

from __future__ import annotations

from collections.abc import Callable

# Mutable test state. Clear it between cases with reset().
pin_constructions: list[tuple] = []
uart_constructions: list[UART] = []
_devices: dict[int, object] = {}
_uart_lines: list[bytes] = []
_uart_bytes = bytearray()
_uart_read_exc: Exception | None = None


def register_device(address: int, device: object) -> None:
    """Add a fake device responder at `address`."""
    _devices[address] = device


def feed_uart(lines: list[bytes]) -> None:
    """Queue byte lines for UART.readline() to return in order (FIFO)."""
    _uart_lines.extend(lines)


def feed_uart_bytes(data: bytes, *, notify: bool = True) -> None:
    """Queue binary UART data for any() and readinto() consumers.

    Args:
        data: Bytes appended to the shared binary receive queue.
        notify: Whether to run each UART's receive-idle callback afterwards,
            as hardware does once the line goes quiet. Pass False to leave an
            IRQ-driven reader waiting on its own timeout instead.
    """
    _uart_bytes.extend(data)
    if notify:
        for uart in uart_constructions:
            uart.trigger_rx_idle()


def fail_uart_reads(exc: Exception | None) -> None:
    """Make the next `UART.readinto()` call raise `exc` instead of returning data.

    The fault is one-shot: it fires on the next call, then clears itself, so a
    test can inject a single error and let the following call recover
    normally. Pass None to cancel a pending fault.

    Args:
        exc: Exception the next `readinto()` call raises, or None to clear.
    """
    global _uart_read_exc  # noqa: PLW0603
    _uart_read_exc = exc


def reset() -> None:
    """Clear recorded constructions, the device registry, and the UART queues."""
    global _uart_read_exc  # noqa: PLW0603
    pin_constructions.clear()
    uart_constructions.clear()
    _devices.clear()
    _uart_lines.clear()
    _uart_bytes.clear()
    _uart_read_exc = None


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


class I2C(_I2CBase):
    """Fake `machine.I2C` (hardware peripheral)."""


class SoftI2C(_I2CBase):
    """Fake `machine.SoftI2C` (bit-banged)."""


class UART:
    """Fake `machine.UART` backed by line and binary receive queues.

    Construction keeps every keyword in `config`, so port-specific settings
    such as `bits`, `parity`, `stop`, `rxbuf`, and `timeout_char` stay
    inspectable without this signature tracking them. `irq()` records a
    receive-idle callback that `machine.feed_uart_bytes(...)` then fires, which
    is how an interrupt-driven driver gets woken on the host.
    """

    # Ports assign their own bit for this trigger, so only its identity
    # matters: irq() records whatever the caller passed and compares it back.
    IRQ_RXIDLE = 1 << 4

    def __init__(
        self,
        id: int | None = None,  # noqa: A002
        *_args: object,
        **kwargs: object,
    ) -> None:
        """Record the positional bus id and every keyword the caller passed."""
        self.id = id
        self.config: dict[str, object] = dict(kwargs)
        self.baudrate = kwargs.get("baudrate", 9600)
        self.tx = kwargs.get("tx")
        self.rx = kwargs.get("rx")
        self.timeout = kwargs.get("timeout", 0)
        self.irq_handler: Callable[[UART], None] | None = None
        self.irq_trigger = 0
        self.irq_hard = False
        self.deinitialized = False
        uart_constructions.append(self)

    def readline(self) -> bytes | None:
        """Return the next queued byte line, or None when the queue is empty."""
        return _uart_lines.pop(0) if _uart_lines else None

    def readinto(self, buf: bytearray, nbytes: int | None = None) -> int | None:
        """Move up to ``nbytes`` queued bytes into ``buf``, or None when empty.

        Args:
            buf: Caller-owned buffer written in place, as drivers reuse.
            nbytes: Byte ceiling; defaults to however much ``buf`` holds.

        Returns:
            The number of bytes written, or None when nothing was queued.

        Raises:
            exc: Whatever `fail_uart_reads()` last armed, raised once instead
                of returning.
        """
        global _uart_read_exc
        if _uart_read_exc is not None:
            exc, _uart_read_exc = _uart_read_exc, None
            raise exc
        limit = len(buf) if nbytes is None else min(nbytes, len(buf))
        count = min(limit, len(_uart_bytes))
        if not count:
            return None
        buf[:count] = _uart_bytes[:count]
        del _uart_bytes[:count]
        return count

    def any(self) -> int:
        """Return how many bytes are waiting in the binary receive queue."""
        return len(_uart_bytes)

    def irq(
        self,
        handler: Callable[[UART], None] | None = None,
        trigger: int = 0,
        *,
        hard: bool = False,
    ) -> UART:
        """Register or clear the receive callback and return the IRQ handle.

        Args:
            handler: Callback to run on a matching trigger, or None to clear.
            trigger: Trigger bitmask; only IRQ_RXIDLE fires under this stub.
            hard: Recorded for inspection. The stub always calls the handler
                as a plain function, since there is no interrupt context here.

        Returns:
            The UART itself, standing in for MicroPython's port-specific IRQ
            object so callers have something to hold and later discard.
        """
        self.irq_handler = handler
        self.irq_trigger = trigger
        self.irq_hard = hard
        return self

    def trigger_rx_idle(self) -> None:
        """Run the registered IRQ_RXIDLE callback, as an idle RX line does."""
        if self.deinitialized or self.irq_handler is None:
            return
        if self.irq_trigger & UART.IRQ_RXIDLE:
            self.irq_handler(self)

    def deinit(self) -> None:
        """Release the UART: drop the callback and mark the instance closed."""
        self.irq_handler = None
        self.irq_trigger = 0
        self.deinitialized = True
