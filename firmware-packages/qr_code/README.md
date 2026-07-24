# qr_code

A deliberately narrow QR encoder: **Version 2 (25×25 modules), error-correction
level L, 8-bit byte mode only**. It exists to render one compact fixed string — a
Wi-Fi credential payload whose 32 bytes fit V2-L's 32-byte byte capacity — so it
trades generality for a guarantee: every successful `encode` returns exactly a
25×25 grid, and anything that does not fit raises `QRError`.

## Layout
```
qr_code/
  qr_code/
    __init__.py   re-exports encode, QRError, SIZE
    qr_code.py    GF(256) Reed-Solomon, matrix placement, mask selection, BCH format bits
```

## Public API
```python
from qr_code import encode, QRError, SIZE   # SIZE == 25

grid = encode("WIFI:T:WPA;S:LFX-1A;P:12345678;;")
# grid is a list of 25 bytearray(25) rows; grid[y][x] == 1 is a dark module.
# No quiet zone is added — the caller frames and scales the modules.
```

`encode` raises `QRError` when the payload exceeds the 32-byte V2-L byte capacity.

## Notes

- **Fixed geometry on purpose.** Version, ECC level, and mode are constants. The
  only caller draws a scaled bitmap and must be able to assume 25×25 always; a
  variable-size encoder would defeat that.
- **Faithful algorithm.** Finder/timing/alignment placement, Reed-Solomon over
  GF(256), the eight data masks with full penalty scoring, and BCH format bits are
  a specialised port of Project Nayuki's QR Code generator. Coordinates follow that
  convention: a module is `grid[y][x]` (row `y`, column `x`), which is also the
  order a framebuffer's `pixel(x, y)` expects.
- **No hardware, no allocation in hot loops.** Pure Python plus 256-entry GF tables
  built once at import; encoding is a one-shot per credential rotation, not a
  per-frame operation.

## Tests
Host tests cover the Version 2-L geometry, the 32-byte capacity boundary,
overflow rejection, and function-pattern placement; the encoder is also verified
end-to-end by scanning the OLED QR produced by the `led-effects` project. Run
them the repo way, from the root:
```
docker compose run --rm --build pytest /firmware-packages/qr_code/tests
```
