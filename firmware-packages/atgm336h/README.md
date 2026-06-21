# atgm336h

MCU package for the ATGM336H GNSS module: reads NMEA sentences over UART. The
package owns *what* pins it needs (the `Wiring` schema); the project's `BOARD`
table owns *which* pins, dispatched per chip.

## Public API
```python
from atgm336h import Wiring, connect

Wiring  # namedtuple("Wiring", ("id", "tx", "rx")) — id selects the UART peripheral

gps = connect(Wiring(id=0, tx=0, rx=1))   # opens the UART at 9600 baud
line = gps.readline()                      # "$GPRMC,..." or None on timeout
```

`readline()` returns one decoded NMEA sentence (starting with `$`), or `None` on
timeout, decode error, or a non-NMEA line.

## Wiring lives in the project
Pin numbers are not in this package. Each project fills `Wiring` per chip in its
`main.py` `BOARD` table via `os.uname().machine` dispatch and passes it to `connect`.

## Tests
```
docker compose up pytest --build --exit-code-from pytest -- /firmware-packages/atgm336h/tests
```
