# atgm336h

MCU package for the ATGM336H GNSS module: reads NMEA sentences over UART. The
constructor takes flat pin numbers and opens its own UART, so the project's
`BOARD` table supplies only pins.

## Public API
```python
from atgm336h import GPS, DeviceNotFoundError

gps = GPS(bus_id=0, tx=0, rx=1)   # opens the UART at 9600 baud + probes for bytes
line = gps.readline()              # "$GPRMC,..." or None when no line is ready
```

`readline()` returns one decoded NMEA sentence (starting with `$`), or `None`
when no complete line is ready, on decode error, or on a non-NMEA line. The constructor raises
`DeviceNotFoundError` if no NMEA bytes arrive within the probe budget (~2 s).

## Pin numbers live in the project
Pin numbers are not in this package. Each project defines its own `BOARD` table
of plain pin numbers in `main.py` via `os.uname().machine` dispatch and passes
them as flat keyword arguments to `GPS()`.

## Tests
```
docker compose up pytest --build --exit-code-from pytest -- /firmware-packages/atgm336h/tests
```
