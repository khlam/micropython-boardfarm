"""Compile reusable Matter firmware with no board credentials.

Runs inside Dockerfile.matter's `matter-toolchain` stage. The stage's ENTRYPOINT
sources ESP-IDF's and ESP-Matter's environments before exec'ing this script
rather than running it directly: each `export.sh` mutates PATH and several dozen
other variables in the calling shell, and there is no way to source one from
inside a Python process.

The paths below are fixed by the Matter stages' mounts and image. provision.py
and pairing_code.py read the ones they share from here.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from matter_tools.build import (
    board_to_identity,
    build_firmware,
    hand_outputs_to_owner,
    merge_image,
    publish,
    validate_merged_image,
)

BOARD_DIR = Path("/matter-board/ESP32_S3_MATTER")
OUTPUT_DIR = Path("/outputs")
# The bind-mounted source, present for compiling and flashing alike, whose owner
# receives the published artifacts.
OWNER_REFERENCE = Path("/matter-board")

_BUILD_CACHE = Path("/build-cache")
_MANIFEST = Path("/manifest.py")
_MATTER_NATIVE = Path("/firmware-packages/matter/native")
_MICROPYTHON_PORT = Path("/opt/micropython/ports/esp32")


def main() -> int:
    """Compile, validate, publish, and return an exit status.

    Every check runs before anything is copied into /outputs, so a rejected build
    leaves the previous artifacts untouched rather than half-replaced.

    Returns:
        The process exit status.
    """
    identity = board_to_identity(BOARD_DIR)
    with tempfile.TemporaryDirectory(prefix="matter-build.") as scratch:
        staging_root = Path(scratch)
        _BUILD_CACHE.mkdir(parents=True, exist_ok=True)
        build_firmware(
            _BUILD_CACHE,
            port_dir=_MICROPYTHON_PORT,
            board_dir=BOARD_DIR,
            manifest=_MANIFEST,
            native_dir=_MATTER_NATIVE,
        )
        merged = merge_image(_BUILD_CACHE, identity, artifact_root=staging_root)
        validate_merged_image(merged, b"\xff" * identity.factory_size, identity)
        publish(OUTPUT_DIR, merged, None, {})
        hand_outputs_to_owner(OUTPUT_DIR, OWNER_REFERENCE)
    sys.stdout.write("Matter firmware ready to provision\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
