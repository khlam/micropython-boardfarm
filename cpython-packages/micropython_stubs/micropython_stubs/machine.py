"""Host CPython stub of MicroPython's `machine` module."""

from __future__ import annotations

from collections.abc import Callable

# Mutable test state. Clear it between cases with reset().
pin_constructions: list[tuple] = []
uart_constructions: list[UART] = []
_devices: dict[int, object] = {}
_uart_rx = bytearray()
_uart_read_exc: Exception | None = None
_uart_write_exc: Exception | None = None
_uart_replies: list[bytes] = []
_spi_instances: list[object] = []
_timer_instances: list[object] = []
_rtc_datetime: tuple = (2000, 1, 1, 5, 0, 0, 0, 0)


def register_device(address: int, device: object) -> None:
    """Add a fake device responder at `address`."""
    _devices[address] = device


def feed_uart(lines: list[bytes]) -> None:
    """Append byte chunks to the shared UART receive buffer (FIFO).

    Chunks need not be whole lines: feeding a sentence in fragments models a
    non-blocking UART that returns only the bytes received so far.

    Args:
        lines: Byte chunks appended, in order, to the receive buffer.
    """
    feed_uart_bytes(b"".join(lines))


def feed_uart_bytes(data: bytes, *, notify: bool = True) -> None:
    """Queue UART data for the any()/read()/readline()/readinto() consumers.

    Args:
        data: Bytes appended to the shared receive buffer.
        notify: Whether to run each UART's receive-idle callback afterwards,
            as hardware does once the line goes quiet. Pass False to leave an
            IRQ-driven reader waiting on its own timeout instead.
    """
    _uart_rx.extend(data)
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


def fail_uart_writes(exc: Exception | None) -> None:
    """Make the next `UART.write()` call raise `exc` instead of sending data.

    One-shot like `fail_uart_reads()`. Pass None to cancel a pending fault.

    Args:
        exc: Exception the next `write()` call raises, or None to clear.
    """
    global _uart_write_exc  # noqa: PLW0603
    _uart_write_exc = exc


def queue_uart_replies(replies: list[bytes]) -> None:
    """Queue one receive-buffer reply per `UART.write()` call (FIFO).

    Models a device that answers each command frame, which a driver awaiting an
    acknowledgement inside its own coroutine cannot otherwise be fed. Writes
    made after the queue empties send nothing back.

    Args:
        replies: Byte strings fed back, in order, one per write.
    """
    _uart_replies.extend(replies)


def reset() -> None:
    """Clear recorded constructions, the device registry, and UART/SPI/Timer/RTC state."""
    global _uart_read_exc, _uart_write_exc, _rtc_datetime  # noqa: PLW0603
    pin_constructions.clear()
    uart_constructions.clear()
    _devices.clear()
    _uart_rx.clear()
    _uart_replies.clear()
    _uart_read_exc = None
    _uart_write_exc = None
    _spi_instances.clear()
    _timer_instances.clear()
    _rtc_datetime = (2000, 1, 1, 5, 0, 0, 0, 0)


class RTC:
    """Fake `machine.RTC` sharing one module-level datetime across instances.

    The real RTC is a single hardware peripheral, so every construction reads and
    writes the same clock; `reset()` returns it to the port's power-on default.
    """

    def datetime(self, value: tuple | None = None) -> tuple | None:
        """Get the stored datetime tuple, or set it when ``value`` is given.

        Args:
            value: ``(year, month, day, weekday, hour, minute, second, subsecond)``
                to store, or ``None`` to read the current value.

        Returns:
            The stored 8-tuple when reading, otherwise ``None``.
        """
        global _rtc_datetime  # noqa: PLW0603
        if value is None:
            return _rtc_datetime
        _rtc_datetime = tuple(value)
        return None


class Pin:
    """Fake `machine.Pin`. Records id + mode, supports value() get/set and irq()."""

    OUT = "OUT"
    IN = "IN"
    PULL_UP = "PULL_UP"
    PULL_DOWN = "PULL_DOWN"
    IRQ_FALLING = "IRQ_FALLING"
    IRQ_RISING = "IRQ_RISING"

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
        self._irq_handler = None
        self._irq_trigger = None
        pin_constructions.append((id, mode))

    def value(self, v: int | None = None) -> int | None:
        """Get or set the pin value (0/1)."""
        if v is None:
            return self._value
        self._value = int(bool(v))
        return None

    def on(self) -> None:
        """Set the pin high."""
        self._value = 1

    def off(self) -> None:
        """Set the pin low."""
        self._value = 0

    def irq(
        self,
        handler: object = None,
        trigger: str | None = None,
        **_kwargs: object,
    ) -> Pin:
        """Record an interrupt handler/trigger; return self as the irq object."""
        self._irq_handler = handler
        self._irq_trigger = trigger
        return self

    def trigger_irq(self) -> None:
        """Test helper: fire the registered IRQ handler as the hardware would."""
        if self._irq_handler is not None:
            self._irq_handler(self)


class SPI:
    """Fake `machine.SPI` that records writes."""

    instances = _spi_instances

    def __init__(
        self,
        id: int | None = None,  # noqa: A002
        *_args: object,
        baudrate: int = 1_000_000,
        polarity: int = 0,
        phase: int = 0,
        sck: object = None,
        mosi: object = None,
        miso: object = None,
        **_kwargs: object,
    ) -> None:
        """Record SPI configuration and start with no writes."""
        self.id = id
        self.baudrate = baudrate
        self.polarity = polarity
        self.phase = phase
        self.sck = sck
        self.mosi = mosi
        self.miso = miso
        self.writes: list[bytes] = []
        _spi_instances.append(self)

    def write(self, buf: bytes) -> None:
        """Record one SPI write payload."""
        self.writes.append(bytes(buf))


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
    """Fake `machine.UART` backed by the shared byte receive buffer.

    Construction keeps every keyword in `config`, so port-specific settings
    such as `bits`, `parity`, `stop`, `rxbuf`, and `timeout_char` stay
    inspectable without this signature tracking them. `irq()` records a
    receive-idle callback that `machine.feed_uart_bytes(...)` then fires, which
    is how an interrupt-driven driver gets woken on the host. Sent frames land
    in `writes`, and `machine.queue_uart_replies(...)` answers them.
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
        self.writes: list[bytes] = []
        uart_constructions.append(self)

    def write(self, data: bytes) -> int:
        """Record one sent frame and feed back its scripted reply, if any.

        Args:
            data: Bytes the driver sent.

        Returns:
            How many bytes were sent, as the real UART reports.

        Raises:
            exc: Whatever `fail_uart_writes()` last armed, raised once instead
                of sending.
        """
        global _uart_write_exc
        if _uart_write_exc is not None:
            exc, _uart_write_exc = _uart_write_exc, None
            raise exc
        self.writes.append(bytes(data))
        if _uart_replies:
            feed_uart_bytes(_uart_replies.pop(0))
        return len(data)

    def any(self) -> int:
        """Return how many bytes are waiting in the receive buffer."""
        return len(_uart_rx)

    def read(self, nbytes: int | None = None) -> bytes | None:
        """Return up to nbytes from the receive buffer, or None when empty.

        Models a non-blocking read: it never waits for more bytes to arrive, so
        a sentence fed in fragments comes back one fragment at a time.

        Args:
            nbytes: Byte ceiling; defaults to everything buffered.

        Returns:
            The bytes taken from the buffer, or None when it is empty.
        """
        if not _uart_rx:
            return None
        if nbytes is None or nbytes >= len(_uart_rx):
            data = bytes(_uart_rx)
            _uart_rx.clear()
            return data
        data = bytes(_uart_rx[:nbytes])
        del _uart_rx[:nbytes]
        return data

    def readline(self) -> bytes | None:
        """Return bytes up to and including the next newline, or None.

        Returns None when no complete line is buffered yet — matching a
        non-blocking UART that does not wait for the rest of the sentence.
        """
        nl = _uart_rx.find(b"\n")
        if nl < 0:
            return None
        data = bytes(_uart_rx[: nl + 1])
        del _uart_rx[: nl + 1]
        return data

    def readinto(self, buf: bytearray, nbytes: int | None = None) -> int | None:
        """Move up to ``nbytes`` buffered bytes into ``buf``, or None when empty.

        Args:
            buf: Caller-owned buffer written in place, as drivers reuse.
            nbytes: Byte ceiling; defaults to however much ``buf`` holds.

        Returns:
            The number of bytes written, or None when nothing was buffered.

        Raises:
            exc: Whatever `fail_uart_reads()` last armed, raised once instead
                of returning.
        """
        global _uart_read_exc
        if _uart_read_exc is not None:
            exc, _uart_read_exc = _uart_read_exc, None
            raise exc
        limit = len(buf) if nbytes is None else min(nbytes, len(buf))
        count = min(limit, len(_uart_rx))
        if not count:
            return None
        buf[:count] = _uart_rx[:count]
        del _uart_rx[:count]
        return count

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


class Timer:
    """Fake `machine.Timer` recording its periodic callback for tests to fire."""

    PERIODIC = "PERIODIC"
    ONE_SHOT = "ONE_SHOT"
    instances = _timer_instances

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        """Register the instance with no callback until init() runs."""
        self.period = None
        self.mode = None
        self.callback = None
        _timer_instances.append(self)

    def init(
        self,
        *,
        period: int = -1,
        mode: str = PERIODIC,
        callback: object = None,
        **_kwargs: object,
    ) -> None:
        """Record the timer configuration and periodic callback."""
        self.period = period
        self.mode = mode
        self.callback = callback

    def deinit(self) -> None:
        """Stop the timer by dropping its callback."""
        self.callback = None

    def tick(self) -> None:
        """Test helper: invoke the periodic callback as the hardware timer would."""
        if self.callback is not None:
            self.callback(self)
