"""Host tests for default and compact Wi-Fi credential profiles."""

import pytest

from wifi import secrets
from wifi.errors import ProvisioningError


def _random_bytes(_length: int) -> bytes:
    """Return deterministic non-identical entropy for secret tests."""
    return bytes(range(1, 33))


def test_default_profile_preserves_existing_lengths():
    """The default profile still emits the original SSID and password sizes."""
    result = secrets.draw("LEDFX-", _random_bytes)

    assert result.ssid == "LEDFX-01020304"
    assert result.password == "05060708090A0B0C0D0E0F10"  # noqa: S105 - fixture value
    assert len(result.csrf) == 32
    assert len(result.qr_payload) == 56


def test_compact_profile_fits_version_two_qr_capacity():
    """The compact profile emits a six-character SSID and eight-character key."""
    result = secrets.draw("LFX-", _random_bytes, ssid_bytes=1, password_bytes=4)

    assert result.ssid == "LFX-01"
    assert result.password == "02030405"  # noqa: S105 - fixture value
    assert len(result.csrf) == 32
    assert len(result.qr_payload.encode()) == 32


def test_compact_profile_rejects_a_short_wpa2_password():
    """Credential generation rejects passwords below the WPA2 minimum."""
    with pytest.raises(ProvisioningError, match="entropy"):
        secrets.draw("LFX-", _random_bytes, ssid_bytes=1, password_bytes=3)
