"""Matter pairing generation from one secret key, shared by MicroPython and host tooling."""

import binascii
import hashlib
import os

_KEY_BYTES = 32
_MIN_PASSCODE_LEN = 24
_MIN_PASSCODE_DISTINCT = 12
_MAX_PASSCODE = 99999999
_INVALID_PASSCODES = (
    11111111,
    22222222,
    33333333,
    44444444,
    55555555,
    66666666,
    77777777,
    88888888,
    99999999,
    12345678,
    87654321,
)
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


def generate_pairing(passcode: str | None = None) -> dict:
    """Derive pairing data from one secret key, drawing a random key when none is given.

    ``passcode`` keys the derivation rather than becoming the Matter setup
    passcode. It is the only input, so boards flashed with the same key share
    their pairing codes.

    Args:
        passcode: Secret key, at least ``_MIN_PASSCODE_LEN`` characters long and
            spanning at least ``_MIN_PASSCODE_DISTINCT`` distinct characters, or
            ``None`` to draw a fresh random one.

    Returns:
        A dictionary with the resolved ``key`` string, the integer ``passcode`` and
        ``discriminator`` derived from it, and the eleven-digit string
        ``manual_pairing_code``.

    Raises:
        ValueError: The key is not a string, is too short, or spans too few
            distinct characters to resist guessing.
    """
    if passcode is None:
        passcode = _random_passcode()
    elif type(passcode) is not str:
        raise ValueError("passcode must be a string")
    elif len(passcode) < _MIN_PASSCODE_LEN:
        raise ValueError(f"passcode must be at least {_MIN_PASSCODE_LEN} characters")
    elif len(set(passcode)) < _MIN_PASSCODE_DISTINCT:
        raise ValueError(
            f"passcode must span at least {_MIN_PASSCODE_DISTINCT} distinct characters"
        )
    digest = hashlib.sha256(b"matter-pairing-v2\x00" + passcode.encode()).digest()
    setup_passcode = int.from_bytes(digest[:4], "big") % _MAX_PASSCODE + 1
    while setup_passcode in _INVALID_PASSCODES:
        setup_passcode = setup_passcode % _MAX_PASSCODE + 1
    discriminator = int.from_bytes(digest[4:6], "big") & 0xFFF
    return {
        "key": passcode,
        "passcode": setup_passcode,
        "discriminator": discriminator,
        "manual_pairing_code": _encode_manual_code(discriminator, setup_passcode),
    }


def _random_passcode() -> str:
    """Draw a random 256-bit key as 64 hexadecimal characters."""
    while True:
        passcode = binascii.hexlify(os.urandom(_KEY_BYTES)).decode()
        # Hex has only sixteen symbols, so a rare draw can span too few distinct
        # characters for generate_pairing to accept it.
        if len(set(passcode)) >= _MIN_PASSCODE_DISTINCT:
            return passcode


def _encode_manual_code(discriminator: int, passcode: int) -> str:
    """Encode the standard Matter manual code, including its Verhoeff digit."""
    short_discriminator = discriminator >> 8
    chunk1 = (short_discriminator >> 2) & 0x3
    chunk2 = ((short_discriminator & 0x3) << 14) | (passcode & 0x3FFF)
    chunk3 = passcode >> 14
    body = f"{chunk1:01d}{chunk2:05d}{chunk3:04d}"
    checksum = 0
    for position, digit in enumerate(reversed(body)):
        permutation = _VERHOEFF_P[(position + 1) % len(_VERHOEFF_P)][int(digit)]
        checksum = _VERHOEFF_D[checksum][permutation]
    return body + str(_VERHOEFF_INV[checksum])
