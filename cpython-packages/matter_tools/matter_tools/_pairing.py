"""Matter pairing generation from one secret key."""

import hashlib
import os

from matter_tools._onboarding_codes import encode_manual_code
from matter_tools._spake2p import INVALID_PASSCODES, MAX_PASSCODE

_KEY_BYTES = 32
_MIN_PASSCODE_LEN = 24
_MIN_PASSCODE_DISTINCT = 12


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
    digest = hashlib.sha256(passcode.encode()).digest()
    setup_passcode = int.from_bytes(digest[:4], "big") % MAX_PASSCODE + 1
    while setup_passcode in INVALID_PASSCODES:
        setup_passcode = setup_passcode % MAX_PASSCODE + 1
    discriminator = int.from_bytes(digest[4:6], "big") & 0xFFF
    return {
        "key": passcode,
        "passcode": setup_passcode,
        "discriminator": discriminator,
        "manual_pairing_code": encode_manual_code(discriminator, setup_passcode),
    }


def _random_passcode() -> str:
    """Draw a random 256-bit key as 64 hexadecimal characters."""
    while True:
        passcode = os.urandom(_KEY_BYTES).hex()
        # Hex has only sixteen symbols, so a rare draw can span too few distinct
        # characters for generate_pairing to accept it.
        if len(set(passcode)) >= _MIN_PASSCODE_DISTINCT:
            return passcode
