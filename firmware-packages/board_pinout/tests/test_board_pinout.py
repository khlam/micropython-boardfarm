"""Host CPython tests for board_pinout: dispatch, pin uniqueness, and the ban.

The `chip` fixture (conftest) patches os.uname so each `import board_pinout`
re-dispatches to the parametrized backend. These assertions are the executable
mirror of the README pin tables — they fail loudly if a board file drifts from
the documented wiring, double-books a GPIO, or re-introduces an underside pad.
"""

import pytest

_RP2040 = "Raspberry Pi Pico with RP2040"
_RP2350 = "Raspberry Pi Pico 2 with RP2350"
_ESP32 = "ESP32S3 module with ESP32S3"
_ALL = [_RP2040, _RP2350, _ESP32]

# (id, sck, mosi, miso) / (id, sda, scl) / (id, tx, rx) per board.
_EXPECTED = {
    _RP2040: {
        "name": "RP2040-Zero",
        "status_led": 16,
        "spi": (1, 10, 11, None),
        "i2c": (0, 0, 1),
        "uart": (1, 4, 5),
        "display_cs": 9,
    },
    _RP2350: {
        "name": "RP2350",
        "status_led": "LED",
        "spi": (1, 10, 11, None),
        "i2c": (0, 0, 1),
        "uart": (1, 4, 5),
        "display_cs": 9,
    },
    _ESP32: {
        "name": "ESP32-S3-Zero",
        "status_led": 21,
        "spi": (1, 12, 11, None),
        "i2c": (0, 1, 2),
        "uart": (1, 17, 18),
        "display_cs": 10,
    },
}

# RP2040-Zero castellated edge GPIO: GP0-GP15 and GP26-GP29.
_RP2040_EDGE = set(range(16)) | set(range(26, 30))


def _physical_pins(board):
    """Every GPIO the board drives: bus signal lines + per-device CS.

    Skips each bus's peripheral id (field 0), unconnected lines (``None`` MISO),
    and I2C addresses — only true GPIO numbers are returned.
    """
    pins = []
    for bus in (board.spi, board.i2c, board.uart):
        pins.extend(line for line in bus[1:] if line is not None)
    pins.extend(dev.cs for dev in board.devices.values() if dev.cs is not None)
    return pins


@pytest.mark.parametrize("chip", _ALL, indirect=True)
def test_dispatch_selects_expected_board(chip):
    import board_pinout

    exp = _EXPECTED[chip]
    board = board_pinout.BOARD
    assert board.name == exp["name"]
    assert board.status_led == exp["status_led"]
    assert tuple(board.spi) == exp["spi"]
    assert tuple(board.i2c) == exp["i2c"]
    assert tuple(board.uart) == exp["uart"]
    assert board.devices["display"].cs == exp["display_cs"]
    assert board.devices["gps"].bus == "uart"


@pytest.mark.parametrize("chip", _ALL, indirect=True)
def test_no_duplicate_physical_pins(chip):
    import board_pinout

    pins = _physical_pins(board_pinout.BOARD)
    assert len(pins) == len(set(pins))


@pytest.mark.parametrize("chip", _ALL, indirect=True)
def test_device_integrity(chip):
    import board_pinout

    for dev in board_pinout.BOARD.devices.values():
        assert dev.bus in ("spi", "i2c", "uart")
        if dev.bus == "spi":
            assert dev.cs is not None
        if dev.bus == "i2c":
            assert dev.addr is not None


@pytest.mark.parametrize("chip", [_RP2040], indirect=True)
def test_rp2040_zero_avoids_underside_pads(chip):
    import board_pinout

    pins = set(_physical_pins(board_pinout.BOARD))
    assert pins.isdisjoint(board_pinout.RP2040_ZERO_BANNED)


@pytest.mark.parametrize("chip", [_RP2040], indirect=True)
def test_rp2040_zero_pins_on_edge_header(chip):
    import board_pinout

    for pin in _physical_pins(board_pinout.BOARD):
        assert pin in _RP2040_EDGE
