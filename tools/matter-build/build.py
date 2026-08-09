"""Build the ESP32-S3 Matter firmware and publish its commissioning artifacts.

Runs inside the `matter-toolchain` stage of Dockerfile.matter. The stage's
ENTRYPOINT sources the ESP-IDF and ESP-Matter environments before exec'ing this
module rather than running it directly: both `export.sh` scripts mutate PATH and
several dozen other variables in the calling shell, and there is no way to source
them from inside a Python process.

Everything that describes the device is read from the board configuration the
firmware itself consumes -- the factory row of partitions.csv and the CONFIG_
entries of sdkconfig.board -- instead of being restated here. A partition table
or vendor ID edited in one place without the other therefore fails the build,
where two independent copies of the same literals would quietly agree with each
other and disagree with the running device.

The checks between minting and publishing decode the QR and manual codes from
scratch rather than trusting the manufacturing tool that produced them, so a
pairing code only reaches /outputs alongside an image it describes. Their logic
is exercised on the host by tests/.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import nvs_partition_gen
import nvs_partition_read
import onboarding_codes
import qr_image
import spake2p

_BOARD_DIR = Path("/matter-board/ESP32_S3_MATTER")
_BUILD_CACHE = Path("/build-cache")
_MANIFEST = Path("/manifest.py")
_MATTER_NATIVE = Path("/firmware-packages/matter/native")
_MICROPYTHON_PORT = Path("/opt/micropython/ports/esp32")
_OUTPUT_DIR = Path("/outputs")
_PROJECT_TOML = Path("/project/pyproject.toml")

# /outputs is bind-mounted from the host, so the artifacts are written as root
# unless they are handed back to whoever owns the equally bind-mounted source.
_OWNER_REFERENCE = Path("/firmware")

_BOARD_NAME = "ESP32_S3_MATTER"
_IDF_TARGET = "esp32s3"
_ARTIFACT_MODE = 0o644

_MERGED_NAME = "app.esp32-s3.bin"
_QR_NAME = "app.esp32-s3.qr.png"
_SETUP_NAME = "app.esp32-s3.setup.txt"

# The complete set of files allowed to exist in /outputs.
_OUTPUT_NAMES = frozenset({_MERGED_NAME, _QR_NAME, _SETUP_NAME})
_STAGING_NAMES = frozenset(f".matter-build.{name}.new" for name in _OUTPUT_NAMES)

# Hardware identity with no board-configuration source and no per-build
# parameter. Discovery mode also reaches the onboarding check, which
# cross-checks it: minting encodes it into the QR payload and the check
# base38-decodes it back out. Vendor name, product name, and serial number are
# per-build instead -- see _parse_args and _pyproject_to_model.

_DISCOVERY_BLE = 2
_DISCOVERY_ON_NETWORK = 4
_DISCOVERY_MODE = _DISCOVERY_BLE | _DISCOVERY_ON_NETWORK
_HARDWARE_VERSION = 1
_HARDWARE_VERSION_STRING = "development"

# Manufacturer default when --manufacturer/MANUFACTURER is not supplied.
_DEFAULT_MANUFACTURER = "kinholam.com"

# esp-matter-mfg-tool's own default when neither was passed on its CLI.
_SPAKE2P_ITERATION_COUNT = 10000
_SPAKE2P_SALT_LEN = 32

_FLASH_SIZE_RE = re.compile(r"^CONFIG_ESPTOOLPY_FLASHSIZE_(\d+)MB$")

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


@dataclass(frozen=True)
class _BuildIdentity:
    """What the firmware believes about itself, read from its board configuration.

    Every field is derived from the files the running device actually consumes --
    the partition table and sdkconfig -- rather than restated as a literal, so
    checking an artifact against this instance compares it against the firmware
    instead of against a second copy of the same constants.
    """

    vendor_id: int
    product_id: int
    factory_offset: int
    factory_size: int
    flash_size: int
    discovery_mode: int


def main() -> int:
    """Build, mint, validate, publish, and return an exit status.

    Every check runs before anything is copied into /outputs, so a rejected build
    leaves the previous artifacts untouched rather than half-replaced.

    Returns:
        The process exit status.
    """
    args = _parse_args()
    passcode = int(args.passcode) if args.passcode else None
    manufacturer = args.manufacturer or _DEFAULT_MANUFACTURER
    serial_number = args.serial_number or _default_serial_number()
    model = _pyproject_to_model(_PROJECT_TOML)
    identity = _board_to_identity(_BOARD_DIR, _DISCOVERY_MODE)
    with tempfile.TemporaryDirectory(prefix="matter-build.") as scratch:
        staging_root = Path(scratch)
        _BUILD_CACHE.mkdir(parents=True, exist_ok=True)
        _build_firmware(_BUILD_CACHE)
        factory, qr, manual, payload, discriminator = _mint_credentials(
            staging_root, identity, manufacturer, serial_number, model, passcode
        )
        merged = _merge_image(
            _BUILD_CACHE,
            factory,
            identity,
            artifact_root=staging_root,
        )
        _validate_merged_image(merged, factory, qr, identity)
        _validate_factory_identity(
            nvs_partition_read.read_factory_partition(factory, nvs_partition_gen.NAMESPACE),
            discriminator,
            identity,
        )
        _publish(merged, qr, manual, payload)
        _hand_outputs_to_owner()
    sys.stdout.write(f"{_OUTPUT_DIR / _MERGED_NAME} and matching commissioning artifacts ready\n")
    return 0


def _parse_args() -> argparse.Namespace:
    """Parse the build's command line."""
    parser = argparse.ArgumentParser(description="Build and publish ESP32-S3 Matter firmware.")
    parser.add_argument(
        "--passcode",
        default="",
        help="setup passcode to mint into this build's credentials; random if omitted",
    )
    parser.add_argument(
        "--manufacturer",
        default="",
        help=f"vendor name to mint into this build's credentials; "
        f"{_DEFAULT_MANUFACTURER!r} if omitted",
    )
    parser.add_argument(
        "--serial-number",
        default="",
        help="serial number to mint into this build's credentials; a build timestamp if omitted",
    )
    return parser.parse_args()


def _board_to_identity(board_dir: Path, discovery_mode: int) -> _BuildIdentity:
    """Read the device's identity and flash layout out of its board configuration."""
    config = _sdkconfig_to_values(board_dir / "sdkconfig.board")
    label = _required(config, "CONFIG_CHIP_FACTORY_NAMESPACE_PARTITION_LABEL").strip('"')
    offset, size = _partitions_to_factory(board_dir / "partitions.csv", label)
    return _BuildIdentity(
        vendor_id=int(_required(config, "CONFIG_DEVICE_VENDOR_ID"), 0),
        product_id=int(_required(config, "CONFIG_DEVICE_PRODUCT_ID"), 0),
        factory_offset=offset,
        factory_size=size,
        flash_size=_config_to_flash_size(config),
        discovery_mode=discovery_mode,
    )


def _sdkconfig_to_values(path: Path) -> dict[str, str]:
    """Parse an sdkconfig fragment into its KEY=value pairs, ignoring comments."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def _required(config: dict[str, str], key: str) -> str:
    """Return one sdkconfig value, failing loudly when the board never sets it."""
    value = config.get(key)
    if value is None:
        raise ValueError(f"board sdkconfig does not set {key}")
    return value


def _partitions_to_factory(path: Path, label: str) -> tuple[int, int]:
    """Return the offset and size of the named partition in an IDF partition table.

    The label comes from the sdkconfig key the firmware uses to find its factory
    namespace, so the row selected here is by construction the row the device
    reads at runtime.
    """
    for row in csv.reader(path.read_text(encoding="utf-8").splitlines()):
        fields = [field.strip() for field in row]
        if not fields or fields[0].startswith("#") or fields[0] != label:
            continue
        if len(fields) < 5 or not fields[3] or not fields[4]:
            raise ValueError(f"partition {label!r} in {path} has no explicit offset and size")
        return int(fields[3], 0), int(fields[4], 0)
    raise ValueError(f"partition table {path} has no {label!r} row")


def _config_to_flash_size(config: dict[str, str]) -> int:
    """Return the configured flash size in bytes from the enabled FLASHSIZE key."""
    for key, value in config.items():
        match = _FLASH_SIZE_RE.match(key)
        if match and value == "y":
            return int(match.group(1)) * 1024 * 1024
    raise ValueError("board sdkconfig enables no CONFIG_ESPTOOLPY_FLASHSIZE_*MB key")


def _pyproject_to_model(path: Path) -> str:
    """Read this build's model name from the project's package metadata."""
    with path.open("rb") as stream:
        project = tomllib.load(stream).get("project")
    name = project.get("name") if isinstance(project, dict) else None
    if not isinstance(name, str) or not name:
        raise ValueError(f"{path} [project] table must set a non-empty name")
    return name


def _default_serial_number() -> str:
    """Mint a build-timestamp serial number when none is supplied."""
    return datetime.now(UTC).strftime("%m.%d.%y.%H.%M.%S")


def _run(
    command: Sequence[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    """Run one toolchain command, resolving it on PATH so a missing tool says so.

    Every executable here is put on PATH by the export.sh scripts the entrypoint
    sources, so an unresolvable name means the environment was never set up --
    worth reporting as itself rather than as a bare FileNotFoundError.
    """
    environment = env if env is not None else dict(os.environ)
    executable = shutil.which(command[0], path=environment.get("PATH"))
    if executable is None:
        raise ValueError(f"{command[0]} is not on PATH; was the toolchain environment sourced?")
    subprocess.run([executable, *command[1:]], check=True, cwd=cwd, env=environment)  # noqa: S603


def _build_firmware(build_root: Path) -> None:
    """Compile MicroPython with the ESP-Matter native module into build_root."""
    _run(
        [
            "idf.py",
            "-C",
            str(_MICROPYTHON_PORT),
            "-B",
            str(build_root / "idf"),
            "-D",
            f"MICROPY_BOARD={_BOARD_NAME}",
            "-D",
            f"MICROPY_BOARD_DIR={_BOARD_DIR}",
            "-D",
            f"MICROPY_FROZEN_MANIFEST={_MANIFEST}",
            "-D",
            f"USER_C_MODULES={_MATTER_NATIVE / 'micropython' / 'micropython.cmake'}",
            "build",
        ],
        env=dict(os.environ, MATTER_NATIVE_PATH=str(_MATTER_NATIVE)),
    )


def _mint_credentials(
    build_root: Path,
    identity: _BuildIdentity,
    manufacturer: str,
    serial_number: str,
    model: str,
    passcode: int | None = None,
) -> tuple[Path, Path, str, str, int]:
    """Generate one device's factory partition, onboarding codes and QR image.

    A caller-supplied passcode is minted into this device's credentials; when
    none is given, a fresh random one is minted here. Either way a fresh
    discriminator and salt are minted each run, so the returned artifacts only
    ever match the image built alongside them.
    """
    outdir = build_root / "manufacturing"
    outdir.mkdir(parents=True, exist_ok=True)

    discriminator = secrets.randbelow(0x1000)
    if passcode is None:
        passcode = _random_passcode()
    salt = secrets.token_bytes(_SPAKE2P_SALT_LEN)
    verifier = spake2p.generate_verifier(passcode, salt, _SPAKE2P_ITERATION_COUNT)

    factory = nvs_partition_gen.write_factory_partition(
        outdir,
        identity.factory_size,
        discriminator=discriminator,
        iteration_count=_SPAKE2P_ITERATION_COUNT,
        salt=salt,
        verifier=verifier,
        identity=nvs_partition_gen.DeviceIdentity(
            vendor_id=identity.vendor_id,
            vendor_name=manufacturer,
            product_id=identity.product_id,
            product_name=model,
            hardware_version=_HARDWARE_VERSION,
            hardware_version_string=_HARDWARE_VERSION_STRING,
            serial_number=serial_number,
        ),
    )

    payload = onboarding_codes.encode_qr_payload(
        identity.vendor_id, identity.product_id, discriminator, passcode, identity.discovery_mode
    )
    manual = onboarding_codes.encode_manual_code(discriminator, passcode)
    _validate_onboarding(payload, manual, discriminator, passcode, identity)

    qr = outdir / "qrcode.png"
    qr_image.render(payload, qr)

    return factory, qr, manual, payload, discriminator


def _random_passcode() -> int:
    """Mint a cryptographically random setup passcode, excluding invalid values."""
    while True:
        passcode = spake2p.MIN_PASSCODE + secrets.randbelow(
            spake2p.MAX_PASSCODE - spake2p.MIN_PASSCODE + 1
        )
        if passcode not in spake2p.INVALID_PASSCODES:
            return passcode


def _merge_image(
    build_root: Path,
    factory: Path,
    identity: _BuildIdentity,
    *,
    artifact_root: Path | None = None,
) -> Path:
    """Combine the IDF build and the factory partition into one flashable image.

    Runs from the IDF build directory because @flash_args names the bootloader,
    partition table and application by paths relative to it. The merged image can
    be staged outside the persistent compilation tree so per-device artifacts do
    not become build-cache state.
    """
    merged = (artifact_root if artifact_root is not None else build_root) / _MERGED_NAME
    _run(
        [
            "esptool.py",
            "--chip",
            _IDF_TARGET,
            "merge_bin",
            "-o",
            str(merged),
            "@flash_args",
            hex(identity.factory_offset),
            str(factory),
        ],
        cwd=build_root / "idf",
    )
    return merged


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

    Kept independent of onboarding_codes._verhoeff_check_digit

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


def _validate_onboarding(
    payload: str,
    manual: str,
    discriminator: int,
    passcode: int,
    identity: _BuildIdentity,
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


def _validate_merged_image(
    merged_path: Path, factory_path: Path, qr_path: Path, identity: _BuildIdentity
) -> None:
    """Check image bounds, factory placement, and QR image presence."""
    merged = merged_path.read_bytes()
    factory = factory_path.read_bytes()
    start = identity.factory_offset
    end = start + identity.factory_size
    if not merged or len(merged) > identity.flash_size:
        raise ValueError(f"merged image exceeds the {identity.flash_size:#x} byte flash layout")
    if len(factory) != identity.factory_size:
        raise ValueError(f"factory partition must be exactly {identity.factory_size:#x} bytes")
    if merged[start:end] != factory:
        raise ValueError(
            f"merged image does not carry the generated factory partition at {start:#x}"
        )
    if not qr_path.is_file() or qr_path.stat().st_size == 0:
        raise ValueError("QR image is missing or empty")


def _validate_factory_identity(values: dict, discriminator: int, identity: _BuildIdentity) -> None:
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


def _publish(merged: Path, qr: Path, manual: str, payload: str) -> None:
    """Publish one matched artifact generation with a fail-closed cutover.

    All three files are staged on the output filesystem before the public pairing
    material is removed. During cutover, the binary is replaced before its matching
    QR and setup text, so an interrupted build never exposes stale credentials beside
    a new image. An advisory lock on the output directory serializes live build
    processes without adding a fourth artifact that could itself become stale.
    """
    with _publication_lock():
        unexpected = sorted(
            path.name
            for path in _OUTPUT_DIR.iterdir()
            if path.name not in _OUTPUT_NAMES and path.name not in _STAGING_NAMES
        )
        if unexpected:
            raise ValueError("unexpected output artifacts: " + ", ".join(unexpected))

        destinations = {name: _OUTPUT_DIR / name for name in _OUTPUT_NAMES}
        staged = {name: _OUTPUT_DIR / f".matter-build.{name}.new" for name in _OUTPUT_NAMES}
        for path in staged.values():
            path.unlink(missing_ok=True)

        try:
            _install(merged, staged[_MERGED_NAME])
            _install(qr, staged[_QR_NAME])
            _write_setup(staged[_SETUP_NAME], manual, payload)

            destinations[_SETUP_NAME].unlink(missing_ok=True)
            destinations[_QR_NAME].unlink(missing_ok=True)
            for name in (_MERGED_NAME, _QR_NAME, _SETUP_NAME):
                _commit_staged(staged[name], destinations[name])
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)


@contextmanager
def _publication_lock() -> Iterator[None]:
    """Hold the output directory's advisory lock for one publication transaction."""
    descriptor = os.open(_OUTPUT_DIR, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _install(source: Path, destination: Path) -> None:
    """Copy one artifact into place with a fixed, readable mode."""
    shutil.copyfile(source, destination)
    destination.chmod(_ARTIFACT_MODE)


def _write_setup(path: Path, manual: str, payload: str) -> None:
    """Write the two-line setup file naming this build's pairing codes."""
    path.write_text(
        f"manual_pairing_code={manual}\nsetup_payload={payload}\n",
        encoding="utf-8",
    )
    path.chmod(_ARTIFACT_MODE)


def _commit_staged(source: Path, destination: Path) -> None:
    """Atomically expose one staged artifact under its public name."""
    source.replace(destination)


def _hand_outputs_to_owner() -> None:
    """Give the finished artifacts to whoever owns the bind-mounted source tree."""
    published = sorted(_OUTPUT_DIR.iterdir())
    if len(published) != len(_OUTPUT_NAMES):
        raise ValueError(f"expected {len(_OUTPUT_NAMES)} artifacts, found {len(published)}")
    owner = _OWNER_REFERENCE.stat()
    for path in [_OUTPUT_DIR, *published]:
        os.chown(path, owner.st_uid, owner.st_gid)


if __name__ == "__main__":
    sys.exit(main())
