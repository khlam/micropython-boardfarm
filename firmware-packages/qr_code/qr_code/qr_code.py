"""Fixed-parameter QR encoder: Version 2, error-correction level L, byte mode.

This module deliberately supports exactly one QR geometry — Version 2 (a 25x25
module grid), ECC level L, 8-bit byte mode — because the only caller renders a
compact fixed Wi-Fi credential string whose 32-byte payload fits the V2-L byte
capacity. Anything that does not fit that single configuration raises ``QRError``
rather than silently producing a differently sized code, so a consumer that
draws a fixed-size bitmap can trust the output is always 25x25.

The algorithm is a faithful, specialised port of Project Nayuki's QR Code
generator: finder/timing/alignment placement, Reed-Solomon over GF(256), the
eight data masks with full penalty scoring, and BCH format bits. Coordinates use
Nayuki's convention throughout — a module is ``grid[y][x]`` (row ``y``, column
``x``) and every helper takes ``(x, y)`` — so the ported logic stays verbatim and
the returned grid indexes as ``grid[y][x]`` (row-major), which is also the order
a framebuffer's ``pixel(x, y)`` wants.

Public API:
    from qr_code import encode, QRError
    grid = encode("WIFI:T:WPA;S:...;;")   # -> list[bytearray], 25 rows x 25 cols
    #   grid[y][x] is 1 for a dark module, 0 for light. No quiet zone is added;
    #   the caller owns quiet-zone framing and pixel scaling.
"""

__all__ = ["SIZE", "QRError", "encode"]

# --- Fixed V2-L parameters --------------------------------------------------
SIZE = 25  # modules per side for Version 2
_VERSION = 2
_ALIGN_POSITIONS = (6, 18)  # alignment-pattern centre coordinates for V2
_NUM_BLOCKS = 1  # error-correction blocks for V2-L
_ECC_PER_BLOCK = 10  # ECC codewords per block for V2-L
_DATA_CODEWORDS = 34  # total data codewords for V2-L
_RAW_CODEWORDS = 44  # data + ECC codewords placed in the matrix (V2)
_BYTE_CAPACITY = 32  # maximum byte-mode characters for V2-L
_ECL_FORMAT_BITS = 1  # level L format indicator (L=1, M=0, Q=3, H=2)

# Penalty weights from the QR specification.
_PENALTY_N1 = 3
_PENALTY_N2 = 3
_PENALTY_N3 = 40
_PENALTY_N4 = 10


class QRError(Exception):
    """The payload does not fit a Version 2 / level-L byte-mode QR code.

    Raised instead of returning a wrongly sized or truncated grid so a caller
    that draws a fixed 25x25 bitmap can treat any successful ``encode`` result as
    exactly that size and fail closed otherwise.
    """


# --- GF(256) arithmetic for Reed-Solomon ------------------------------------
# Antilog/log tables for the field with primitive polynomial 0x11D, generator 2.
# Built once at import; 256-entry tables are cheap and avoid per-call allocation.
_GF_EXP = bytearray(512)
_GF_LOG = bytearray(256)


def _init_gf() -> None:
    """Populate the GF(256) exponent and log tables."""
    x = 1
    for i in range(255):
        _GF_EXP[i] = x
        _GF_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _GF_EXP[i] = _GF_EXP[i - 255]


_init_gf()


def _gf_mul(a: int, b: int) -> int:
    """Multiply two GF(256) elements."""
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_divisor(degree: int) -> bytearray:
    """Return the Reed-Solomon generator polynomial of the given degree.

    Coefficients are ordered from the highest power down, with the implicit
    leading 1 omitted (length == ``degree``), matching ``_rs_remainder``.
    """
    result = bytearray(degree)
    result[degree - 1] = 1
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 2)
    return result


def _rs_remainder(data: bytearray, divisor: bytearray) -> bytearray:
    """Compute the Reed-Solomon ECC codewords for ``data``."""
    degree = len(divisor)
    result = bytearray(degree)
    for b in data:
        factor = b ^ result[0]
        # Shift one place left. MicroPython bytearrays support neither item
        # deletion nor pop(), so the shift is done in place.
        for j in range(degree - 1):
            result[j] = result[j + 1]
        result[degree - 1] = 0
        for j in range(degree):
            result[j] ^= _gf_mul(divisor[j], factor)
    return result


# --- Bit buffer -------------------------------------------------------------
class _BitBuffer:
    """Accumulates a big-endian bit stream into whole bytes."""

    def __init__(self) -> None:
        self.bytes = bytearray()
        self._acc = 0
        self._nbits = 0

    def append(self, value: int, length: int) -> None:
        """Append the low ``length`` bits of ``value``, most significant first."""
        for i in range(length - 1, -1, -1):
            self._acc = (self._acc << 1) | ((value >> i) & 1)
            self._nbits += 1
            if self._nbits == 8:
                self.bytes.append(self._acc)
                self._acc = 0
                self._nbits = 0

    def bit_length(self) -> int:
        """Return the number of bits appended so far."""
        return len(self.bytes) * 8 + self._nbits

    def pad_to_byte(self) -> None:
        """Zero-pad the pending partial byte, if any, to a byte boundary."""
        if self._nbits:
            self.append(0, 8 - self._nbits)


# --- Encoding ---------------------------------------------------------------
def _data_codewords(payload: bytes) -> bytearray:
    """Build the 34 data codewords for the byte-mode payload."""
    buf = _BitBuffer()
    buf.append(0b0100, 4)  # byte-mode indicator
    buf.append(len(payload), 8)  # character count (8 bits for V1-9 byte mode)
    for b in payload:
        buf.append(b, 8)
    capacity_bits = _DATA_CODEWORDS * 8
    buf.append(0, min(4, capacity_bits - buf.bit_length()))  # terminator
    buf.pad_to_byte()
    codewords = buf.bytes
    pad = (0xEC, 0x11)
    while len(codewords) < _DATA_CODEWORDS:
        codewords.append(pad[len(codewords) % 2])
    return codewords


def _interleave(codewords: bytearray) -> bytearray:
    """Split data into blocks, append ECC, and interleave to placement order."""
    per_block = _DATA_CODEWORDS // _NUM_BLOCKS
    divisor = _rs_divisor(_ECC_PER_BLOCK)
    data_blocks = []
    ecc_blocks = []
    for i in range(_NUM_BLOCKS):
        block = codewords[i * per_block : (i + 1) * per_block]
        data_blocks.append(block)
        ecc_blocks.append(_rs_remainder(block, divisor))
    result = bytearray()
    for i in range(per_block):
        for block in data_blocks:
            result.append(block[i])
    for i in range(_ECC_PER_BLOCK):
        for block in ecc_blocks:
            result.append(block[i])
    return result


# --- Matrix construction ----------------------------------------------------
def _new_grid() -> list:
    """Return a fresh SIZE x SIZE grid of zero bytes."""
    return [bytearray(SIZE) for _ in range(SIZE)]


def _set_function(grid: list, func: list, x: int, y: int, dark: int) -> None:
    """Set a function module at ``(x, y)`` and mark it reserved."""
    grid[y][x] = 1 if dark else 0
    func[y][x] = 1


def _draw_finder(grid: list, func: list, cx: int, cy: int) -> None:
    """Draw a finder pattern (and its separator) centred at ``(cx, cy)``."""
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            dist = max(abs(dx), abs(dy))
            x, y = cx + dx, cy + dy
            if 0 <= x < SIZE and 0 <= y < SIZE:
                _set_function(grid, func, x, y, dist not in (2, 4))


def _draw_alignment(grid: list, func: list, cx: int, cy: int) -> None:
    """Draw an alignment pattern centred at ``(cx, cy)``."""
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            _set_function(grid, func, cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)


def _draw_function_patterns(grid: list, func: list) -> None:
    """Draw finders, separators, timing, alignment, and the dark module."""
    for i in range(SIZE):
        _set_function(grid, func, 6, i, i % 2 == 0)
        _set_function(grid, func, i, 6, i % 2 == 0)
    _draw_finder(grid, func, 3, 3)
    _draw_finder(grid, func, SIZE - 4, 3)
    _draw_finder(grid, func, 3, SIZE - 4)
    positions = _ALIGN_POSITIONS
    last = len(positions) - 1
    for i, py in enumerate(positions):
        for j, px in enumerate(positions):
            # Skip the three positions that collide with the finder corners.
            if (i, j) in ((0, 0), (0, last), (last, 0)):
                continue
            _draw_alignment(grid, func, px, py)
    # Reserve the format-info regions; the values are written per mask later.
    _draw_format(grid, func, 0, reserve_only=True)
    # The dark module is always set (row 4*version+9, column 8).
    _set_function(grid, func, 8, 4 * _VERSION + 9, 1)


def _draw_format(grid: list, func: list, mask: int, *, reserve_only: bool = False) -> None:
    """Write (or reserve) the 15 BCH-protected format-info modules."""
    data = (_ECL_FORMAT_BITS << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    bits = ((data << 10) | rem) ^ 0x5412  # 15-bit format string

    def place(x: int, y: int, index: int) -> None:
        func[y][x] = 1
        if not reserve_only:
            grid[y][x] = (bits >> index) & 1

    for i in range(6):
        place(8, i, i)
    place(8, 7, 6)
    place(8, 8, 7)
    place(7, 8, 8)
    for i in range(9, 15):
        place(14 - i, 8, i)
    for i in range(8):
        place(SIZE - 1 - i, 8, i)
    for i in range(8, 15):
        place(8, SIZE - 15 + i, i)


def _draw_codewords(grid: list, func: list, data: bytearray) -> None:
    """Place the interleaved codeword bits in the standard zig-zag order."""
    bit = 0
    total_bits = len(data) * 8
    col = SIZE - 1
    while col >= 1:
        if col == 6:  # skip the vertical timing column
            col = 5
        for vert in range(SIZE):
            for j in range(2):
                x = col - j
                upward = ((col + 1) & 2) == 0
                y = (SIZE - 1 - vert) if upward else vert
                if not func[y][x] and bit < total_bits:
                    grid[y][x] = (data[bit >> 3] >> (7 - (bit & 7))) & 1
                    bit += 1
        col -= 2


def _apply_mask(grid: list, func: list, mask: int) -> None:
    """XOR the data modules with the given mask pattern (self-inverse)."""
    for y in range(SIZE):
        row = grid[y]
        frow = func[y]
        for x in range(SIZE):
            if frow[x]:
                continue
            if mask == 0:
                invert = (x + y) % 2 == 0
            elif mask == 1:
                invert = y % 2 == 0
            elif mask == 2:
                invert = x % 3 == 0
            elif mask == 3:
                invert = (x + y) % 3 == 0
            elif mask == 4:
                invert = (x // 3 + y // 2) % 2 == 0
            elif mask == 5:
                invert = (x * y) % 2 + (x * y) % 3 == 0
            elif mask == 6:
                invert = ((x * y) % 2 + (x * y) % 3) % 2 == 0
            else:
                invert = ((x + y) % 2 + (x * y) % 3) % 2 == 0
            if invert:
                row[x] ^= 1


def _finder_penalty_count(history: list) -> int:
    """Count finder-like 1:1:3:1:1 runs in the sliding run history."""
    n = history[1]
    core = n > 0 and history[2] == n and history[3] == n * 3 and history[4] == n and history[5] == n
    return (1 if core and history[0] >= n * 4 and history[6] >= n else 0) + (
        1 if core and history[6] >= n * 4 and history[0] >= n else 0
    )


def _finder_penalty_add(run: int, history: list) -> None:
    """Push a run length onto the finder-penalty history.

    The very first run (recognised by an all-zero history) is padded by one
    module side to account for the light border, matching the specification.
    """
    if history[0] == 0:
        run += SIZE
    history.insert(0, run)
    history.pop()


def _finder_penalty_terminate(color: int, run: int, history: list) -> int:
    """Flush the final run (with light border) and count finder patterns."""
    if color:
        _finder_penalty_add(run, history)
        run = 0
    run += SIZE
    _finder_penalty_add(run, history)
    return _finder_penalty_count(history)


def _penalty_line(get) -> int:  # noqa: ANN001
    """Score one axis (rows or columns) for run and finder penalties."""
    result = 0
    for major in range(SIZE):
        color = 0
        run = 0
        history = [0] * 7
        for minor in range(SIZE):
            pixel = get(major, minor)
            if pixel == color:
                run += 1
                if run == 5:
                    result += _PENALTY_N1
                elif run > 5:
                    result += 1
            else:
                _finder_penalty_add(run, history)
                if color == 0:
                    result += _finder_penalty_count(history) * _PENALTY_N3
                color = pixel
                run = 1
        result += _finder_penalty_terminate(color, run, history) * _PENALTY_N3
    return result


def _penalty(grid: list) -> int:
    """Compute the total QR penalty score for mask selection."""
    result = _penalty_line(lambda y, x: grid[y][x])  # rows
    result += _penalty_line(lambda x, y: grid[y][x])  # columns
    for y in range(SIZE - 1):
        for x in range(SIZE - 1):
            c = grid[y][x]
            if c == grid[y][x + 1] and c == grid[y + 1][x] and c == grid[y + 1][x + 1]:
                result += _PENALTY_N2
    dark = sum(sum(row) for row in grid)
    total = SIZE * SIZE
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    return result + k * _PENALTY_N4


def encode(text: str) -> list:
    """Encode ``text`` as a Version 2 / level-L byte-mode QR code.

    Args:
        text: The payload string; encoded as UTF-8 bytes (ASCII in practice).

    Returns:
        A 25-row list of ``bytearray(25)`` where each entry is 1 for a dark
        module and 0 for a light module. No quiet zone is included.

    Raises:
        QRError: If the payload exceeds the 32-byte V2-L byte capacity.
    """
    payload = text.encode()
    if len(payload) > _BYTE_CAPACITY:
        raise QRError("payload exceeds Version 2-L byte capacity")

    data = _interleave(_data_codewords(payload))
    grid = _new_grid()
    func = _new_grid()
    _draw_function_patterns(grid, func)
    _draw_codewords(grid, func, data)

    best_mask = 0
    best_penalty = -1
    for mask in range(8):
        _apply_mask(grid, func, mask)
        _draw_format(grid, func, mask)
        penalty = _penalty(grid)
        if best_penalty < 0 or penalty < best_penalty:
            best_penalty = penalty
            best_mask = mask
        _apply_mask(grid, func, mask)  # undo (mask XOR is self-inverse)

    _apply_mask(grid, func, best_mask)
    _draw_format(grid, func, best_mask)
    return grid
