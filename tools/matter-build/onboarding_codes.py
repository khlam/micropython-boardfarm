"""Encode a Matter QR setup payload for one device.

The mirror image of build.py's `_decode_qr_payload`: same bit widths, same field
order, same Base38 alphabet, so a value encoded here and decoded there
round-trips exactly. This project uses standard commissioning flow only.
"""

from __future__ import annotations

from spake2p import MAX_PASSCODE, MIN_PASSCODE

_BASE38 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."
_BASE38_CHARS_PER_CHUNK = {1: 2, 2: 4, 3: 5}

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
