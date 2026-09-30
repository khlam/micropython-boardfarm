"""Compile reusable Matter firmware and publish it with any pairing artifacts.

Everything that describes the device is read from the board configuration the
firmware itself consumes -- the factory row of partitions.csv and the CONFIG_
entries of sdkconfig.board -- instead of being restated here. A partition table
or vendor ID edited in one place without the other therefore fails the build,
where two independent copies of the same literals would quietly agree with each
other and disagree with the running device.

Toolchain commands resolve on PATH, so callers run with ESP-IDF's environment
(and, to compile, ESP-Matter's) already sourced.
"""

from __future__ import annotations

import csv
import fcntl
import gzip
import os
import re
import shutil
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DISCOVERY_MODE",
    "IDF_TARGET",
    "MERGED_NAME",
    "QR_NAME",
    "SETUP_NAME",
    "BoardIdentity",
    "board_to_identity",
    "build_firmware",
    "hand_outputs_to_owner",
    "merge_image",
    "publish",
    "run",
    "stage_dashboard",
    "validate_merged_image",
]

IDF_TARGET = "esp32s3"

MERGED_NAME = "app.esp32-s3.bin"
QR_NAME = "app.esp32-s3.qr.png"
SETUP_NAME = "app.esp32-s3.setup.txt"

# Hardware identity with no board-configuration source and no flash-time
# parameter. Discovery mode also reaches the onboarding check, which
# cross-checks it: minting encodes it into the QR payload and the check
# base38-decodes it back out. Vendor name, product name, and serial number are
# supplied at flash time -- see provision.mint_credentials.
_DISCOVERY_BLE = 2
_DISCOVERY_ON_NETWORK = 4
DISCOVERY_MODE = _DISCOVERY_BLE | _DISCOVERY_ON_NETWORK

_BOARD_NAME = "ESP32_S3_MATTER"
_ARTIFACT_MODE = 0o644

# The complete set of files allowed to exist in the output directory.
_OUTPUT_NAMES = frozenset({MERGED_NAME, QR_NAME, SETUP_NAME})
_STAGING_NAMES = frozenset(f".matter-build.{name}.new" for name in _OUTPUT_NAMES)

_FLASH_SIZE_RE = re.compile(r"^CONFIG_ESPTOOLPY_FLASHSIZE_(\d+)MB$")


@dataclass(frozen=True)
class BoardIdentity:
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


def board_to_identity(board_dir: Path) -> BoardIdentity:
    """Read the device's identity and flash layout out of its board configuration."""
    config = _sdkconfig_to_values(board_dir / "sdkconfig.board")
    label = _required(config, "CONFIG_CHIP_FACTORY_NAMESPACE_PARTITION_LABEL").strip('"')
    offset, size = _partitions_to_factory(board_dir / "partitions.csv", label)
    return BoardIdentity(
        vendor_id=int(_required(config, "CONFIG_DEVICE_VENDOR_ID"), 0),
        product_id=int(_required(config, "CONFIG_DEVICE_PRODUCT_ID"), 0),
        factory_offset=offset,
        factory_size=size,
        flash_size=_config_to_flash_size(config),
        discovery_mode=DISCOVERY_MODE,
    )


def run(command: Sequence[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    """Run one toolchain command, resolving it on PATH so a missing tool says so.

    Every executable here is put on PATH by the export.sh scripts the caller's
    entrypoint sources, so an unresolvable name means the environment was never
    set up -- worth reporting as itself rather than as a bare FileNotFoundError.
    """
    environment = env if env is not None else dict(os.environ)
    executable = shutil.which(command[0], path=environment.get("PATH"))
    if executable is None:
        raise ValueError(f"{command[0]} is not on PATH; was the toolchain environment sourced?")
    subprocess.run([executable, *command[1:]], check=True, cwd=cwd, env=environment)  # noqa: S603


def stage_dashboard(source: Path, staging_root: Path) -> Path | None:
    """Turn the project's dashboard page into a module, and return its directory.

    Freeze the authored HTML as gzip bytes because the board has no filesystem
    partition. The server sends those bytes without expanding them. Stage them
    outside the read-only /firmware mount for manifest.py's FROZEN_STAGING_DIR.

    Args:
        source: The project's dashboard page, which may not exist.
        staging_root: Scratch directory this build owns for the whole run.

    Returns:
        The directory to freeze, or None when the project has no dashboard.
    """
    if not source.is_file():
        return None
    # mtime=0 so the same page keeps producing the same firmware image.
    body = gzip.compress(source.read_bytes(), compresslevel=9, mtime=0)
    staged = staging_root / "frozen"
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "dashboard_page.py").write_text(
        '"""The project dashboard, generated from its viz/static/index.html."""\n\n'
        'ENCODING = "gzip"\n'
        f"PAGE = {body!r}\n"
    )
    return staged


def build_firmware(
    build_root: Path,
    staged: Path | None,
    *,
    port_dir: Path,
    board_dir: Path,
    manifest: Path,
    native_dir: Path,
) -> None:
    """Compile MicroPython with the ESP-Matter native module into build_root.

    Remove cached sdkconfig so idf.py applies the board's SDKCONFIG_DEFAULTS on
    every build. There is no interactive configuration to preserve; identical
    regenerated contents leave compiled objects untouched.

    Args:
        build_root: Directory the IDF build tree lives in.
        staged: Directory of build-generated modules to freeze, or None when the
            build generated none. Reaches the manifest as FROZEN_STAGING_DIR.
        port_dir: MicroPython's ESP32 port directory.
        board_dir: The project's board definition directory.
        manifest: The frozen-module manifest.
        native_dir: The ESP-Matter native bridge the build links in.
    """
    (build_root / "idf" / "sdkconfig").unlink(missing_ok=True)
    run(
        [
            "idf.py",
            "-C",
            str(port_dir),
            "-B",
            str(build_root / "idf"),
            "-D",
            f"MICROPY_BOARD={_BOARD_NAME}",
            "-D",
            f"MICROPY_BOARD_DIR={board_dir}",
            "-D",
            f"MICROPY_FROZEN_MANIFEST={manifest}",
            "-D",
            f"USER_C_MODULES={native_dir / 'micropython' / 'micropython.cmake'}",
            "build",
        ],
        env=dict(
            os.environ,
            MATTER_NATIVE_PATH=str(native_dir),
            FROZEN_STAGING_DIR=str(staged or ""),
        ),
    )


def merge_image(
    build_root: Path,
    identity: BoardIdentity,
    *,
    artifact_root: Path,
) -> Path:
    """Combine the IDF build into a reusable image with an empty factory partition.

    Runs from the IDF build directory because @flash_args names the bootloader,
    partition table and application by paths relative to it. The merged image is
    staged outside the persistent compilation tree so published artifacts do not
    become build-cache state.
    """
    merged = artifact_root / MERGED_NAME
    run(
        [
            "esptool.py",
            "--chip",
            IDF_TARGET,
            "merge_bin",
            "--fill-flash-size",
            f"{identity.flash_size // (1024 * 1024)}MB",
            "-o",
            str(merged),
            "@flash_args",
        ],
        cwd=build_root / "idf",
    )
    return merged


def validate_merged_image(merged_path: Path, factory: bytes, identity: BoardIdentity) -> None:
    """Check image size and that the image carries exactly this factory partition.

    The merged image is padded to the whole flash, so anything else means the
    merge did not produce the layout the board is about to be written with. A
    compiled image carries an erased partition, a provisioned one the board's own.
    """
    merged = merged_path.read_bytes()
    start = identity.factory_offset
    end = start + identity.factory_size
    if len(merged) != identity.flash_size:
        raise ValueError(f"merged image must be exactly {identity.flash_size:#x} bytes")
    if len(factory) != identity.factory_size:
        raise ValueError(f"factory partition must be exactly {identity.factory_size:#x} bytes")
    if merged[start:end] != factory:
        raise ValueError(
            f"merged image does not carry the expected factory partition at {start:#x}"
        )


def publish(output_dir: Path, merged: Path, qr: Path | None, setup: dict[str, str]) -> None:
    """Publish one matched artifact generation with a fail-closed cutover.

    Without a QR, only the binary is published. All published files are staged on
    the output filesystem before public pairing material is removed. During
    cutover, the binary is replaced before its matching QR and setup text, so an
    interrupted build never exposes stale credentials beside a new image. An
    advisory lock on the output directory serializes live build processes without
    adding a fourth artifact that could itself become stale.
    """
    with _publication_lock(output_dir):
        unexpected = sorted(
            path.name
            for path in output_dir.iterdir()
            if path.name not in _OUTPUT_NAMES and path.name not in _STAGING_NAMES
        )
        if unexpected:
            raise ValueError("unexpected output artifacts: " + ", ".join(unexpected))

        destinations = {name: output_dir / name for name in _OUTPUT_NAMES}
        staged = {name: output_dir / f".matter-build.{name}.new" for name in _OUTPUT_NAMES}
        for path in staged.values():
            path.unlink(missing_ok=True)

        try:
            _install(merged, staged[MERGED_NAME])
            if qr is not None:
                _install(qr, staged[QR_NAME])
                _write_setup(staged[SETUP_NAME], setup)

            destinations[SETUP_NAME].unlink(missing_ok=True)
            destinations[QR_NAME].unlink(missing_ok=True)
            names = (MERGED_NAME,) if qr is None else (MERGED_NAME, QR_NAME, SETUP_NAME)
            for name in names:
                _commit_staged(staged[name], destinations[name])
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)


def hand_outputs_to_owner(output_dir: Path, owner_reference: Path) -> None:
    """Give the finished artifacts to whoever owns owner_reference.

    The output directory is bind-mounted from the host, so the artifacts are
    written as root unless they are handed back to whoever owns the equally
    bind-mounted source.
    """
    published = sorted(output_dir.iterdir())
    if {path.name for path in published} not in ({MERGED_NAME}, _OUTPUT_NAMES):
        raise ValueError("expected firmware alone or firmware with matching pairing artifacts")
    owner = owner_reference.stat()
    for path in [output_dir, *published]:
        os.chown(path, owner.st_uid, owner.st_gid)


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


@contextmanager
def _publication_lock(output_dir: Path) -> Iterator[None]:
    """Hold the output directory's advisory lock for one publication transaction."""
    descriptor = os.open(output_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _install(source: Path, destination: Path) -> None:
    """Copy one artifact into place with a fixed, readable mode."""
    shutil.copyfile(source, destination)
    destination.chmod(_ARTIFACT_MODE)


def _write_setup(path: Path, setup: dict[str, str]) -> None:
    """Write one ``key=value`` line per setup field."""
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in setup.items()),
        encoding="utf-8",
    )
    path.chmod(_ARTIFACT_MODE)


def _commit_staged(source: Path, destination: Path) -> None:
    """Atomically expose one staged artifact under its public name."""
    source.replace(destination)
