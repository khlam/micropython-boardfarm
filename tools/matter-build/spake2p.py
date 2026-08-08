"""Derive a Matter SPAKE2+ verifier from a passcode, salt and iteration count.

Follows the same PBKDF2-then-curve-math construction as connectedhomeip's
`scripts/tools/spake2p/spake2p.py` (Project CHIP, Apache-2.0), but needs no
elliptic-curve library beyond `cryptography`: a private key's public key is,
by definition, scalar*generator, so `ec.derive_private_key(w1, ...)` followed
by `.public_key()` computes the SPAKE2+ `L = w1*G` term without any
point-arithmetic API.
"""

from __future__ import annotations

import hashlib
import struct

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

# Forbidden passcodes per the Matter spec, "5.1.7.1. Invalid Passcodes"
# (repdigits and the two runs, excluded because they're guessable).
INVALID_PASSCODES = frozenset(
    {
        0,
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
    }
)

MIN_PASSCODE = 1
MAX_PASSCODE = 99999999
MIN_ITERATION_COUNT = 1000
MAX_ITERATION_COUNT = 100000
MIN_SALT_LEN = 16
MAX_SALT_LEN = 32

_CURVE = ec.SECP256R1()
# NIST P-256 (secp256r1) group order n. Verified empirically against
# `cryptography` rather than trusted from transcription: derive_private_key
# rejects a private value only when it is congruent to 0 mod n, so probing
# candidate +/- {1,2,3} around this constant confirmed it's exactly n.
_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_ELEMENT_LEN = 32  # P-256 field element length in bytes
_WS_LEN = _ELEMENT_LEN + 8  # PBKDF2 over-derives 8 extra bytes per element


def generate_verifier(passcode: int, salt: bytes, iteration_count: int) -> bytes:
    """Derive the 97-byte SPAKE2+ verifier (w0 || L) for one device.

    Args:
        passcode: An 8-digit setup passcode, not one of INVALID_PASSCODES.
        salt: 16 to 32 random octets, unique per device.
        iteration_count: PBKDF2 iteration count, 1000 to 100000.

    Returns:
        97 bytes: w0 (32 bytes) followed by the uncompressed point L (65 bytes,
        0x04 || X || Y), matching the format `esp-matter-mfg-tool` wrote today.

    Raises:
        ValueError: The passcode, salt, or iteration count is out of range.
    """
    if not MIN_PASSCODE <= passcode <= MAX_PASSCODE or passcode in INVALID_PASSCODES:
        raise ValueError(f"invalid passcode {passcode}")
    if not MIN_SALT_LEN <= len(salt) <= MAX_SALT_LEN:
        raise ValueError(f"salt must be {MIN_SALT_LEN} to {MAX_SALT_LEN} bytes, got {len(salt)}")
    if not MIN_ITERATION_COUNT <= iteration_count <= MAX_ITERATION_COUNT:
        raise ValueError(
            f"iteration count must be {MIN_ITERATION_COUNT} to {MAX_ITERATION_COUNT}, "
            f"got {iteration_count}"
        )

    ws = hashlib.pbkdf2_hmac(
        "sha256", struct.pack("<I", passcode), salt, iteration_count, _WS_LEN * 2
    )
    w0 = int.from_bytes(ws[:_WS_LEN], byteorder="big") % _ORDER
    w1 = int.from_bytes(ws[_WS_LEN:], byteorder="big") % _ORDER

    l_point = (
        ec.derive_private_key(w1, _CURVE)
        .public_key()
        .public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    )
    return w0.to_bytes(_ELEMENT_LEN, byteorder="big") + l_point
