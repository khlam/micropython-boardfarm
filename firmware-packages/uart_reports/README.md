# uart_reports

Internal reader for radars that stream fixed-length reports framed by a
constant header and footer. Consumed only by drivers; the project never sees
this package.

## Public API
```python
from uart_reports import DeviceNotFoundError, ReportStream

class LD2450(ReportStream):
    def __init__(self, *, bus_id, tx, rx):
        super().__init__(
            name="LD2450", bus_id=bus_id, tx=tx, rx=rx,
            baudrate=256_000, header=b"\xaa\xff\x03\x00", footer=b"\x55\xcc",
            report_len=30,
        )

    def _decode(self, report):
        """Convert one validated report into this driver's targets."""
```

`ReportStream` opens the UART, registers an RX-idle interrupt, and exposes the
lifecycle every radar driver shares:

| Member | What it does |
|---|---|
| `wait_ready()` | Runs `_prepare()`, then waits up to 2 s for a first valid report. Raises `DeviceNotFoundError` if none arrives, closing the UART. |
| `read_latest()` | Drains the UART and decodes only the newest complete report. Returns the targets, `()` when the radar saw nobody, or `None` after 500 ms. |
| `close()` | Idempotent; disables wakeups and deinitializes the UART. |
| `_prepare()` | Optional override for a radar that must be commanded into a mode before it streams. Writes go to `self._uart`. |
| `_decode(report)` | Required override; receives one framed, validated report. |

Only one coroutine may read a stream at a time; a second concurrent call raises
`RuntimeError`. Older complete reports are validated but never decoded, so a
slow caller pays for one decode rather than for the backlog.

## Resynchronization
Bytes are matched one at a time. A candidate whose footer does not match is not
thrown away: an embedded header keeps its remainder, and a trailing partial
header is retained as a prefix, so a stream that starts mid-report locks on
without waiting for the radar to pause.

## Pin numbers live in the project
Pin numbers are not in this package. Each project defines its own `BOARD` table
of plain pin numbers in `main.py` via `os.uname().machine` dispatch and passes
them as flat keyword arguments to the driver, which forwards them here.

## Tests
```
docker compose up pytest --build --exit-code-from pytest -- /firmware-packages/uart_reports/tests
```
