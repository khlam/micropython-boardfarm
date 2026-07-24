"""Host tests for the fixed Version 2-L QR encoder."""

import pytest

import qr_code

_PAYLOAD = "WIFI:T:WPA;S:LFX-1A;P:12345678;;"


def test_encode_returns_version_two_geometry():
    """A successful encode returns a 25x25 row-major module grid."""
    grid = qr_code.encode(_PAYLOAD)

    assert qr_code.SIZE == 25
    assert len(grid) == 25
    assert all(len(row) == 25 for row in grid)


def test_encode_accepts_the_full_byte_capacity():
    """The compact Wi-Fi payload exactly fills the Version 2-L byte capacity."""
    assert len(_PAYLOAD.encode()) == 32
    grid = qr_code.encode(_PAYLOAD)

    assert len(grid) == qr_code.SIZE


def test_encode_rejects_payload_above_capacity():
    """Oversized input fails instead of returning a differently sized QR."""
    with pytest.raises(qr_code.QRError, match="Version 2-L"):
        qr_code.encode("A" * 33)


def test_encode_preserves_function_patterns():
    """Finder and alignment centers remain unmasked function modules."""
    grid = qr_code.encode(_PAYLOAD)

    for cx, cy in ((3, 3), (21, 3), (3, 21)):
        assert grid[cy][cx] == 1
        assert grid[cy][cx + 1] == 1
        assert grid[cy][cx + 2] == 0
    assert grid[18][18] == 1
    assert grid[18][17] == 0
