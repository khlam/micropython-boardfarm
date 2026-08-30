"""Internal fixed-length UART report reader, consumed only by radar drivers.

A radar streams fixed-size reports framed by a constant header and footer, and
every one of them is read the same way: an RX-idle interrupt wakes one asyncio
reader, which drains the UART a byte at a time through a resynchronizing
matcher and keeps only the newest complete report. That machinery lives here
once. A driver subclasses :class:`ReportStream`, declares its framing as class
attributes, and decodes the bytes; the project never sees this package.

Example (inside a driver):
    from uart_reports import DeviceNotFoundError, ReportStream

    class LD2450(ReportStream):
        NAME = "LD2450"
        BAUDRATE = 256_000
        HEADER = b"..."   # the constant bytes each report starts with
        FOOTER = b"..."   # and the ones it ends with
        REPORT_LEN = 30
        STARTUP_TIMEOUT_MS = 2_000
        REPORT_TIMEOUT_MS = 500

        def _decode(self, report):
            ...
"""

import asyncio

import utime
from micropython import const

# A 512-byte UART ring holds well over a second of any supported radar. The
# drain buffer fits four whole reports and is reused for every UART read.
_UART_RX_BUFFER_LEN = const(512)
_DRAIN_BUFFER_REPORTS = const(4)


class DeviceNotFoundError(Exception):
    """No radar answered on the opened UART.

    Drivers raise this (instead of a generic ``OSError``) once startup expires
    so a project's retry loop can tell "nothing on this UART" — bad wiring,
    power, or baud rate — apart from "radar present but the UART failed".
    """


class ReportStream:
    """Own an IRQ-driven UART connection and hand back its newest report.

    Every value below is part of the contract: a subclass declares all seven,
    decodes a validated report in :meth:`_decode`, and may command the device
    before it streams by overriding :meth:`_prepare`.
    """

    NAME = ""  # device name carried by this driver's error messages
    BAUDRATE = 0  # line speed the radar streams at
    HEADER = b""  # constant bytes every report starts with
    FOOTER = b""  # constant bytes every report ends with
    REPORT_LEN = 0  # total report size, header and footer included
    STARTUP_TIMEOUT_MS = 0  # how long detection waits for a first report
    REPORT_TIMEOUT_MS = 0  # how long read_latest() waits for a report

    def __init__(self, *, bus_id: int, tx: int, rx: int) -> None:
        """Open the radar UART and enable receive-idle wakeups.

        Args:
            bus_id: UART number used by the microcontroller.
            tx: GPIO number connected to the radar receive pin.
            rx: GPIO number connected to the radar transmit pin.
        """
        from machine import UART, Pin  # noqa: PLC0415

        self._uart = UART(
            bus_id,
            baudrate=self.BAUDRATE,
            bits=8,
            parity=None,
            stop=1,
            tx=Pin(tx),
            rx=Pin(rx),
            rxbuf=_UART_RX_BUFFER_LEN,
            timeout=0,
            timeout_char=0,
        )
        self._rx_ready = asyncio.ThreadSafeFlag()
        self._drain_buffer = bytearray(self.REPORT_LEN * _DRAIN_BUFFER_REPORTS)
        self._candidate = bytearray(self.REPORT_LEN)
        self._candidate_len = 0
        self._latest_report = bytearray(self.REPORT_LEN)
        self._has_latest_report = False
        self._pending = None
        self._ready = False
        self._reading = False
        self._closed = False
        self._irq = self._uart.irq(
            handler=self._on_rx_idle,
            trigger=UART.IRQ_RXIDLE,
            hard=False,
        )

    async def wait_ready(self) -> None:
        """Prepare the radar and retain its first report for ``read_latest()``.

        Raises:
            DeviceNotFoundError: If preparation failed or no valid report
                arrived within the startup budget.
            OSError: If the UART connection fails.
            RuntimeError: If the driver is closed or already has an active reader.
        """
        if self._closed:
            raise RuntimeError(f"{self.NAME} is closed")
        if self._ready:
            return

        self._claim_reader()
        try:
            await self._prepare()
            targets = await self._wait_for_latest(self.STARTUP_TIMEOUT_MS)
        except (DeviceNotFoundError, OSError):
            self.close()
            raise
        finally:
            self._reading = False

        if targets is None:
            self.close()
            raise DeviceNotFoundError(
                f"no valid {self.NAME} report within {self.STARTUP_TIMEOUT_MS} ms"
            )
        self._pending = targets
        self._ready = True

    async def read_latest(self) -> tuple | None:
        """Return the decoded targets of the newest available report.

        The UART is drained before returning, so older complete reports are
        validated but not decoded. An empty tuple means the newest report saw
        nobody. ``None`` means no complete report arrived in time.

        Returns:
            The detected targets, an empty tuple, or ``None`` after a timeout.

        Raises:
            OSError: If reading the UART connection fails.
            RuntimeError: If startup is incomplete, the driver is closed, or
                another coroutine is reading.
        """
        if self._closed:
            raise RuntimeError(f"{self.NAME} is closed")
        if not self._ready:
            raise RuntimeError("call wait_ready() before read_latest()")

        self._claim_reader()
        try:
            self._drain_uart()
            targets = self._take_latest_targets()
            if targets is None:
                targets = self._pending
            self._pending = None
            if targets is not None:
                return targets
            return await self._wait_for_latest(self.REPORT_TIMEOUT_MS)
        except OSError:  # noqa: TRY203 - make the indirect UART failure contract explicit.
            raise
        finally:
            self._reading = False

    def close(self) -> None:
        """Disable receive wakeups and release the owned UART."""
        if self._closed:
            return
        self._closed = True
        try:
            self._uart.irq(handler=None)
            self._irq = None
        finally:
            self._uart.deinit()

    async def _prepare(self) -> None:
        """Command the radar into the mode this driver decodes.

        Runs once, inside ``wait_ready()``, with the reader claimed and before
        any report is drained. A radar that needs no commanding inherits this.
        """

    def _decode(self, report: bytes | bytearray) -> tuple:
        """Convert one framed, validated report into the driver's targets.

        Args:
            report: The complete report, header and footer included.

        Returns:
            The targets the report describes, empty when it saw nobody.

        Raises:
            NotImplementedError: The subclass did not supply a decoder.
        """
        raise NotImplementedError

    def _claim_reader(self) -> None:
        """Reserve the single IRQ flag waiter for the calling coroutine.

        Raises:
            RuntimeError: Another coroutine is already reading this driver.
        """
        if self._reading:
            raise RuntimeError(f"{self.NAME} already has an active reader")
        self._reading = True

    def _on_rx_idle(self, _uart: object) -> None:
        """Wake the asyncio reader after the UART receive line becomes idle."""
        self._rx_ready.set()

    async def _wait_for_latest(self, timeout_ms: int) -> tuple | None:
        """Drain on each wake until a valid report arrives or time expires.

        Args:
            timeout_ms: Budget for a complete report to arrive.

        Returns:
            The decoded targets, or ``None`` once the budget expires.
        """
        started_ms = utime.ticks_ms()
        while True:
            self._drain_uart()
            targets = self._take_latest_targets()
            if targets is not None:
                return targets

            elapsed_ms = utime.ticks_diff(utime.ticks_ms(), started_ms)
            remaining_ms = timeout_ms - elapsed_ms
            if remaining_ms <= 0:
                self._drain_uart()
                return self._take_latest_targets()

            try:
                await asyncio.wait_for_ms(self._rx_ready.wait(), remaining_ms)
            except asyncio.TimeoutError:  # noqa: UP041 - distinct on MicroPython.
                self._drain_uart()
                return self._take_latest_targets()

    def _drain_uart(self) -> None:
        """Read every available UART byte into the bounded report synchronizer."""
        while True:
            count = self._uart.readinto(self._drain_buffer)
            if not count:
                return
            for index in range(count):
                self._feed_byte(self._drain_buffer[index])

    def _feed_byte(self, value: int) -> None:
        """Advance report synchronization with one received byte."""
        header = self.HEADER
        if self._candidate_len < len(header):
            if value == header[self._candidate_len]:
                self._candidate[self._candidate_len] = value
                self._candidate_len += 1
            elif value == header[0]:
                self._candidate[0] = value
                self._candidate_len = 1
            else:
                self._candidate_len = 0
            return

        self._candidate[self._candidate_len] = value
        self._candidate_len += 1
        if self._candidate_len == self.REPORT_LEN:
            self._finish_candidate()

    def _finish_candidate(self) -> None:
        """Keep a valid report as newest or retain bytes useful for resync."""
        if self._candidate.endswith(self.FOOTER):
            self._candidate, self._latest_report = self._latest_report, self._candidate
            self._has_latest_report = True
            self._candidate_len = 0
            return
        self._resynchronize_candidate()

    def _resynchronize_candidate(self) -> None:
        """Retain an embedded header or partial header after a bad footer."""
        header = self.HEADER
        header_at = self._candidate.find(header, 1)
        if header_at >= 0:
            retained = self.REPORT_LEN - header_at
            for index in range(retained):
                self._candidate[index] = self._candidate[header_at + index]
            self._candidate_len = retained
            return

        for length in range(len(header) - 1, 0, -1):
            if self._candidate.endswith(header[:length]):
                suffix_at = self.REPORT_LEN - length
                for index in range(length):
                    self._candidate[index] = self._candidate[suffix_at + index]
                self._candidate_len = length
                return
        self._candidate_len = 0

    def _take_latest_targets(self) -> tuple | None:
        """Decode and clear the newest valid raw report, if one is available."""
        if not self._has_latest_report:
            return None
        self._has_latest_report = False
        return self._decode(self._latest_report)
