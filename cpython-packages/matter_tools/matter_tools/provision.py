"""Mint, check, and flash one physical board's Matter credentials.

The checks between minting and publishing decode the QR and manual codes from
scratch rather than trusting the encoders that produced them, so a pairing code
only reaches the outputs alongside an image it describes.
"""

from __future__ import annotations

import secrets
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from matter_tools import (
    _nvs_partition_gen,
    _nvs_partition_read,
    _onboarding_codes,
    _qr_image,
    _spake2p,
)
from matter_tools._pairing import generate_pairing
from matter_tools.build import IDF_TARGET, BoardIdentity

__all__ = [
    "DEFAULT_MANUFACTURER",
    "default_serial_number",
    "flash_command",
    "generate_pairing",
    "mint_credentials",
    "provision_image",
    "pyproject_to_model",
    "render_pairing_qr",
    "validate_factory_partition",
    "validate_qr",
]

# Manufacturer used when the caller supplies none.
DEFAULT_MANUFACTURER = "kinholam.com"

_HARDWARE_VERSION = 1
_HARDWARE_VERSION_STRING = "development"

# esp-matter-mfg-tool's own default when neither was passed on its CLI.
_SPAKE2P_ITERATION_COUNT = 10000
_SPAKE2P_SALT_LEN = 32

_BASE38 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."

# Verhoeff algorithm's multiplication,
# permutation, and inverse tables,
# used by _verhoeff_check_digit

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


def pyproject_to_model(path: Path) -> str:
    """Read this build's model name from the project's package metadata."""
    with path.open("rb") as stream:
        project = tomllib.load(stream).get("project")
    name = project.get("name") if isinstance(project, dict) else None
    if not isinstance(name, str) or not name:
        raise ValueError(f"{path} [project] table must set a non-empty name")
    return name


def default_serial_number() -> str:
    """Mint a flash-timestamp serial number when none is supplied."""
    return datetime.now(UTC).strftime("%m.%d.%y.%H.%M.%S")


def mint_credentials(
    build_root: Path,
    identity: BoardIdentity,
    manufacturer: str,
    serial_number: str,
    model: str,
    pairing: dict,
) -> tuple[Path, Path, str]:
    """Generate one board's factory partition, QR payload, and QR image from its pairing."""
    outdir = build_root / "manufacturing"
    outdir.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(_SPAKE2P_SALT_LEN)
    verifier = _spake2p.generate_verifier(pairing["passcode"], salt, _SPAKE2P_ITERATION_COUNT)

    factory = _nvs_partition_gen.write_factory_partition(
        outdir,
        identity.factory_size,
        discriminator=pairing["discriminator"],
        iteration_count=_SPAKE2P_ITERATION_COUNT,
        salt=salt,
        verifier=verifier,
        identity=_nvs_partition_gen.DeviceIdentity(
            vendor_id=identity.vendor_id,
            vendor_name=manufacturer,
            product_id=identity.product_id,
            product_name=model,
            hardware_version=_HARDWARE_VERSION,
            hardware_version_string=_HARDWARE_VERSION_STRING,
            serial_number=serial_number,
        ),
    )

    qr = outdir / "qrcode.png"
    return factory, qr, render_pairing_qr(identity, pairing, qr)


def render_pairing_qr(identity: BoardIdentity, pairing: dict, path: Path) -> str:
    """Render the board's QR at path and return its payload, checked against the manual code."""
    discriminator = pairing["discriminator"]
    passcode = pairing["passcode"]
    payload = _onboarding_codes.encode_qr_payload(
        identity.vendor_id, identity.product_id, discriminator, passcode, identity.discovery_mode
    )
    _validate_onboarding(payload, pairing["manual_pairing_code"], discriminator, passcode, identity)
    _qr_image.render(payload, path)
    return payload


def provision_image(image: bytes, factory: bytes, identity: BoardIdentity) -> bytes:
    """Return the compiled image with one board's factory partition in place."""
    start = identity.factory_offset
    return image[:start] + factory + image[start + identity.factory_size :]


def validate_qr(qr_path: Path) -> None:
    """Check that the rendered QR image exists and is not empty."""
    if not qr_path.is_file() or qr_path.stat().st_size == 0:
        raise ValueError("QR image is missing or empty")


def validate_factory_partition(path: Path, discriminator: int, identity: BoardIdentity) -> None:
    """Read a minted factory partition back and check it against the board's pairing."""
    _validate_factory_identity(
        _nvs_partition_read.read_factory_partition(path, _nvs_partition_gen.NAMESPACE),
        discriminator,
        identity,
    )


def flash_command(port: str, image: Path) -> list[str]:
    """Return the esptool command that writes a whole image, restarting only local boards."""
    # esptool cannot reset a board it reaches over TCP.
    remote = port.startswith(("socket://", "rfc2217://"))
    return [
        "esptool.py",
        "--chip",
        IDF_TARGET,
        "--port",
        port,
        "--before",
        "no_reset" if remote else "default_reset",
        "--after",
        "no_reset" if remote else "watchdog_reset",
        "write_flash",
        "-z",
        "0x0",
        str(image),
    ]


def _validate_onboarding(
    payload: str,
    manual: str,
    discriminator: int,
    passcode: int,
    identity: BoardIdentity,
) -> None:
    """Cross-check the QR and manual code generated for one device."""
    qr_fields = _decode_qr_payload(payload)
    expected_qr = {
        "version": 0,
        "vendor_id": identity.vendor_id,
        "product_id": identity.product_id,
        "commissioning_flow": 0,
        "discovery": identity.discovery_mode,
        "discriminator": discriminator,
        "passcode": passcode,
        "padding": 0,
    }
    if qr_fields != expected_qr:
        raise ValueError("QR payload fields do not match build identity")
    manual_fields = _decode_manual_code(manual)
    if manual_fields != {
        "short_discriminator": discriminator >> 8,
        "passcode": passcode,
    }:
        raise ValueError("manual pairing code does not match QR payload")


def _decode_qr_payload(payload: str) -> dict[str, int]:
    """Decode the fixed Matter setup fields from a standard QR payload."""
    if not payload.startswith("MT:"):
        raise ValueError("setup payload must start with MT:")
    encoded = payload[3:]
    raw = bytearray()
    while encoded:
        length = min(5, len(encoded))
        chunk, encoded = encoded[:length], encoded[length:]
        byte_count = {2: 1, 4: 2, 5: 3}.get(length)
        if byte_count is None:
            raise ValueError("invalid base38 chunk length")
        value = 0
        multiplier = 1
        for character in chunk:
            try:
                digit = _BASE38.index(character)
            except ValueError as error:
                raise ValueError("invalid base38 character") from error
            value += digit * multiplier
            multiplier *= 38
        if value >= 1 << (byte_count * 8):
            raise ValueError("base38 chunk overflows")
        raw.extend(value.to_bytes(byte_count, "little"))
    packed = int.from_bytes(raw, "little")
    return {
        "version": packed & 0x7,
        "vendor_id": (packed >> 3) & 0xFFFF,
        "product_id": (packed >> 19) & 0xFFFF,
        "commissioning_flow": (packed >> 35) & 0x3,
        "discovery": (packed >> 37) & 0xFF,
        "discriminator": (packed >> 45) & 0xFFF,
        "passcode": (packed >> 57) & 0x7FFFFFF,
        "padding": (packed >> 84) & 0xF,
    }


def _decode_manual_code(code: str) -> dict[str, int]:
    """Decode passcode and short discriminator from a standard manual code.

    Args:
        code: The 11-digit manual pairing code, digits only or grouped with
            dashes.

    Returns:
        A dict with the decoded "short_discriminator" and "passcode".

    Raises:
        ValueError: If code is malformed, its trailing digit is not the
            Verhoeff check digit its body requires, or it marks a
            non-standard commissioning flow.
    """
    digits = code.replace("-", "")
    if len(digits) != 11 or not digits.isdigit():
        raise ValueError("manual pairing code must contain 11 digits")
    body, check_digit = digits[:-1], digits[-1]
    if check_digit != _verhoeff_check_digit(body):
        raise ValueError("manual pairing code check digit does not match its body")
    chunk1 = int(body[0])
    chunk2 = int(body[1:6])
    chunk3 = int(body[6:10])
    if chunk1 & 0x4:
        raise ValueError("only standard commissioning flow is supported")
    return {
        "short_discriminator": ((chunk1 & 0x3) << 2) | ((chunk2 >> 14) & 0x3),
        "passcode": (chunk2 & 0x3FFF) | (chunk3 << 14),
    }


def _verhoeff_check_digit(body: str) -> str:
    """Recompute the Verhoeff check digit a manual code's leading digits require.

    Kept independent of the encoder in _pairing.py.

    Args:
        body: The 10 decimal digits preceding the check digit.

    Returns:
        The single decimal Verhoeff check digit body requires.
    """
    checksum = 0
    for position, digit in enumerate(reversed(body)):
        permutation = _VERHOEFF_P[(position + 1) % len(_VERHOEFF_P)][int(digit)]
        checksum = _VERHOEFF_D[checksum][permutation]
    return str(_VERHOEFF_INV[checksum])


def _validate_factory_identity(values: dict, discriminator: int, identity: BoardIdentity) -> None:
    """Check factory identity and that the passcode is stored only as a verifier."""
    if values.get("discriminator") != discriminator:
        raise ValueError("factory discriminator does not match onboarding data")
    if (
        values.get("vendor-id") != identity.vendor_id
        or values.get("product-id") != identity.product_id
    ):
        raise ValueError("factory VID/PID does not match the firmware's board configuration")
    if (
        "passcode" in values
        or not isinstance(values.get("salt"), str)
        or not isinstance(values.get("verifier"), str)
    ):
        raise ValueError("factory data must contain a verifier and no plaintext passcode")
