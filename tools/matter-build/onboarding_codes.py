"""Encode a Matter QR setup payload and manual pairing code for one device.

The mirror image of build.py's `_decode_qr_payload`/`_decode_manual_code`: same
bit widths, same field order, same Base38 alphabet, so a value encoded here and
decoded there round-trips exactly. This project uses standard commissioning
flow only.
"""

from __future__ import annotations

from spake2p import MAX_PASSCODE, MIN_PASSCODE

_BASE38 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."
_BASE38_CHARS_PER_CHUNK = {1: 2, 2: 4, 3: 5}

_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)

_DISCRIMINATOR_BITS = 0xFFF


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
    # Version, standard commissioning flow, and padding are all zero, so only
    # nonzero fields need to participate in the packed value.
    packed = (
        (vendor_id << 3)
        | (product_id << 19)
        | (discovery << 37)
        | (discriminator << 45)
        | (passcode << 57)
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
    return body + _verhoeff_check_digit(body)


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


def _verhoeff_check_digit(body: str) -> str:
    """Return the check digit required for interoperability with Matter commissioners.

    Args:
        body: Decimal digits preceding the check digit.

    Returns:
        The single decimal Verhoeff check digit.
    """
    checksum = 0
    for position, digit in enumerate(reversed(body)):
        permutation = _VERHOEFF_P[(position + 1) % len(_VERHOEFF_P)][int(digit)]
        checksum = _VERHOEFF_D[checksum][permutation]
    return str(_VERHOEFF_INV[checksum])


def _check_discriminator(discriminator: int) -> None:
    if not 0 <= discriminator <= _DISCRIMINATOR_BITS:
        raise ValueError(
            f"discriminator must be 0 to {_DISCRIMINATOR_BITS:#x}, got {discriminator}"
        )


def _check_passcode(passcode: int) -> None:
    if not MIN_PASSCODE <= passcode <= MAX_PASSCODE:
        raise ValueError(f"passcode must be {MIN_PASSCODE} to {MAX_PASSCODE}, got {passcode}")
