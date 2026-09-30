"""Provision and flash one physical board with the image build.py compiled.

Runs inside Dockerfile.matter's `matter-flash` stage, whose ENTRYPOINT sources
ESP-IDF's environment first for the same reason build.py's does.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import build

from matter_tools.build import (
    DISCOVERY_MODE,
    MERGED_NAME,
    BoardIdentity,
    board_to_identity,
    hand_outputs_to_owner,
    publish,
    run,
    validate_merged_image,
)
from matter_tools.provision import (
    DEFAULT_MANUFACTURER,
    default_serial_number,
    flash_command,
    generate_pairing,
    mint_credentials,
    provision_image,
    pyproject_to_model,
    validate_factory_partition,
    validate_qr,
)


def main() -> int:
    """Provision, validate, flash, publish, and return an exit status.

    Every check runs before anything is copied into /outputs, so a rejected board
    leaves the previous artifacts untouched rather than half-replaced.

    Returns:
        The process exit status.
    """
    args = _parse_args()
    identity = board_to_identity(build.BOARD_DIR, DISCOVERY_MODE)
    with tempfile.TemporaryDirectory(prefix="matter-provision.") as scratch:
        _provision_board(Path(scratch), identity, args)
        hand_outputs_to_owner(build.OUTPUT_DIR, build.OWNER_REFERENCE)
    sys.stdout.write("Matter flash complete\n")
    return 0


def _parse_args() -> argparse.Namespace:
    """Parse the provisioning command line."""
    parser = argparse.ArgumentParser(description="Provision and flash one ESP32-S3 Matter board.")
    parser.add_argument("--port", default="/dev/ttyACM0", help="serial port to flash")
    parser.add_argument(
        "--passcode",
        default="",
        help="secret pairing key; a fresh random key if blank",
    )
    parser.add_argument(
        "--manufacturer",
        default="",
        help=f"vendor name; {DEFAULT_MANUFACTURER!r} if omitted",
    )
    parser.add_argument(
        "--serial-number",
        default="",
        help="serial number; a timestamp if omitted",
    )
    return parser.parse_args()


def _provision_board(staging_root: Path, identity: BoardIdentity, args: argparse.Namespace) -> None:
    """Provision the connected board, flash a validated image, then publish its codes."""
    pairing = generate_pairing(args.passcode or None)
    factory, qr, payload = mint_credentials(
        staging_root,
        identity,
        args.manufacturer or DEFAULT_MANUFACTURER,
        args.serial_number or default_serial_number(),
        pyproject_to_model(build.PROJECT_TOML),
        pairing,
    )
    partition = factory.read_bytes()
    merged = staging_root / MERGED_NAME
    merged.write_bytes(
        provision_image((build.OUTPUT_DIR / MERGED_NAME).read_bytes(), partition, identity)
    )
    validate_merged_image(merged, partition, identity)
    validate_qr(qr)
    validate_factory_partition(factory, pairing["discriminator"], identity)
    run(flash_command(args.port, merged))
    publish(
        build.OUTPUT_DIR,
        merged,
        qr,
        {
            "manual_pairing_code": pairing["manual_pairing_code"],
            "setup_payload": payload,
            "passcode": pairing["key"],
        },
    )


if __name__ == "__main__":
    sys.exit(main())
