"""Host CPython stub of MicroPython's `machine` module."""

from __future__ import annotations

# Mutable test state. Clear it between cases with reset().
pin_constructions: list[tuple] = []
_devices: dict[int, object] = {}
_uart_lines: list[bytes] = []
_spi_instances: list[object] = []
_timer_instances: list[object] = []


def register_device(address: int, device: object) -> None:
    """Add a fake device responder at `address`."""
    _devices[address] = device


def feed_uart(lines: list[bytes]) -> None:
    """Queue byte lines for UART.readline() to return in order (FIFO)."""
    _uart_lines.extend(lines)


def reset() -> None:
    """Clear recorded pin constructions, the device registry, UART/SPI/Timer state."""
    pin_constructions.clear()
    _devices.clear()
    _uart_lines.clear()
    _spi_instances.clear()
    _timer_instances.clear()


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
    """Fake `machine.UART` backed by a queued byte-line reader."""

    def __init__(
        self,
        id: int | None = None,  # noqa: A002
        *_args: object,
        baudrate: int = 9600,
        tx: object = None,
        rx: object = None,
        timeout: int = 0,
        timeout_char: int = 0,
        **_kwargs: object,
    ) -> None:
        """Record the positional bus id and UART timing kwargs."""
        self.id = id
        self.baudrate = baudrate
        self.tx = tx
        self.rx = rx
        self.timeout = timeout
        self.timeout_char = timeout_char

    def readline(self) -> bytes | None:
        """Return the next queued byte line, or None when the queue is empty."""
        return _uart_lines.pop(0) if _uart_lines else None


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
