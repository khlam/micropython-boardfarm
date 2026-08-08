"""Encode a Matter QR setup payload and manual pairing code for one device.

The mirror image of build.py's `_decode_qr_payload`/`_decode_manual_code`: same
bit widths, same field order, same Base38 alphabet, so a value encoded here and
decoded there round-trips exactly. Standard commissioning flow only, matching
what this project's onboarding data has ever contained.
"""

from __future__ import annotations

from spake2p import MAX_PASSCODE, MIN_PASSCODE
from stdnum.verhoeff import calc_check_digit

_BASE38 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."
_BASE38_CHARS_PER_CHUNK = {1: 2, 2: 4, 3: 5}

_DISCRIMINATOR_BITS = 0xFFF
_STANDARD_FLOW = 0


def encode_qr_payload(
    vendor_id: int, product_id: int, discriminator: int, passcode: int, discovery: int
) -> str:
    """Build the "MT:..." QR setup payload for one device, standard flow only.

    Args:
        vendor_id: 16-bit vendor ID.
        product_id: 16-bit product ID.
        discriminator: 12-bit long discriminator.
        passcode: The setup passcode minted alongside the SPAKE2+ verifier.
        discovery: The discovery-capabilities bitmask (e.g. 2 for BLE).

    Returns:
        The setup payload string, e.g. "MT:-24J0AFN00KA0648G00".
    """
    _check_discriminator(discriminator)
    _check_passcode(passcode)
    packed = (
        0  # version
        | (vendor_id << 3)
        | (product_id << 19)
        | (_STANDARD_FLOW << 35)
        | (discovery << 37)
        | (discriminator << 45)
        | (passcode << 57)
        | (0 << 84)  # padding
    )
    return "MT:" + _base38_encode(packed.to_bytes(11, byteorder="little"))


def encode_manual_code(discriminator: int, passcode: int) -> str:
    """Build the 11-digit manual pairing code for one device, standard flow only.

    Args:
        discriminator: 12-bit long discriminator.
        passcode: The setup passcode minted alongside the SPAKE2+ verifier.

    Returns:
        The 11-digit manual pairing code, e.g. "34970112332".
    """
    _check_discriminator(discriminator)
    _check_passcode(passcode)
    short_discriminator = discriminator >> 8
    chunk1 = (short_discriminator >> 2) & 0x3
    chunk2 = ((short_discriminator & 0x3) << 14) | (passcode & 0x3FFF)
    chunk3 = passcode >> 14
    body = f"{chunk1:01d}{chunk2:05d}{chunk3:04d}"
    return body + calc_check_digit(body)


def _base38_encode(raw: bytes) -> str:
    """Base38-encode raw bytes in 3-byte chunks, least-significant chunk first."""
    encoded = []
    for offset in range(0, len(raw), 3):
        chunk = raw[offset : offset + 3]
        char_count = _BASE38_CHARS_PER_CHUNK[len(chunk)]
        value = int.from_bytes(chunk, byteorder="little")
        for _ in range(char_count):
            value, digit = divmod(value, 38)
            encoded.append(_BASE38[digit])
    return "".join(encoded)


def _check_discriminator(discriminator: int) -> None:
    if not 0 <= discriminator <= _DISCRIMINATOR_BITS:
        raise ValueError(
            f"discriminator must be 0 to {_DISCRIMINATOR_BITS:#x}, got {discriminator}"
        )


def _check_passcode(passcode: int) -> None:
    if not MIN_PASSCODE <= passcode <= MAX_PASSCODE:
        raise ValueError(f"passcode must be {MIN_PASSCODE} to {MAX_PASSCODE}, got {passcode}")
