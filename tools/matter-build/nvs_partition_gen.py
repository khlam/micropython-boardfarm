"""Generate the "chip-factory" NVS partition binary for one device.

Wraps Espressif's own `esp-idf-nvs-partition-gen` PyPI package -- a standalone,
actively maintained release of the same `nvs_partition_gen.py` ESP-IDF ships
under `components/nvs_flash/nvs_partition_generator/` -- instead of shelling out
to a third-party manufacturing tool. The field set and types below match what
that manufacturing tool actually wrote for this project's device identity: a
commissionable-data-only "chip-factory" namespace with no attestation
certificate chain, since this project has never passed `--paa`/`--pai`/`--cert`.
"""

from __future__ import annotations

import base64
import csv
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from esp_idf_nvs_partition_gen.nvs_partition_gen import generate

NAMESPACE = "chip-factory"
_CSV_NAME = "factory-partition.csv"
_BIN_NAME = "factory-partition.bin"
_NVS_VERSION = 2  # multipage blob support enabled


@dataclass(frozen=True)
class DeviceIdentity:
    """The device-label fields written into the factory partition verbatim.

    Grouped separately from the per-build commissioning secrets (discriminator,
    salt, verifier) because these come from the project's static constants
    rather than being minted fresh each run.
    """

    vendor_id: int
    vendor_name: str
    product_id: int
    product_name: str
    hardware_version: int
    hardware_version_string: str
    software_version: int
    software_version_string: str
    serial_number: str


def write_factory_partition(
    outdir: Path,
    size: int,
    *,
    discriminator: int,
    iteration_count: int,
    salt: bytes,
    verifier: bytes,
    identity: DeviceIdentity,
) -> Path:
    """Write one device's factory NVS partition binary into outdir.

    Args:
        outdir: Directory to write the CSV and binary into; must already exist.
        size: Partition size in bytes, a multiple of 4096.
        discriminator: 12-bit commissioning discriminator.
        iteration_count: SPAKE2+ PBKDF2 iteration count.
        salt: SPAKE2+ salt, 16 to 32 bytes.
        verifier: The 97-byte SPAKE2+ verifier from spake2p.generate_verifier.
        identity: The device's vendor/product/hardware/software/serial labels.

    Returns:
        Path to the generated factory-partition.bin.
    """
    rows = [
        ("discriminator", "data", "u32", str(discriminator)),
        ("iteration-count", "data", "u32", str(iteration_count)),
        ("salt", "data", "string", base64.b64encode(salt).decode("ascii")),
        ("vendor-id", "data", "u32", str(identity.vendor_id)),
        ("vendor-name", "data", "string", identity.vendor_name),
        ("product-id", "data", "u32", str(identity.product_id)),
        ("product-name", "data", "string", identity.product_name),
        ("hardware-ver", "data", "u32", str(identity.hardware_version)),
        ("hw-ver-str", "data", "string", identity.hardware_version_string),
        ("sw-ver", "data", "u32", str(identity.software_version)),
        ("sw-ver-str", "data", "string", identity.software_version_string),
        ("serial-num", "data", "string", identity.serial_number),
        ("verifier", "data", "string", base64.b64encode(verifier).decode("ascii")),
    ]

    csv_path = outdir / _CSV_NAME
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["key", "type", "encoding", "value"])
        writer.writerow([NAMESPACE, "namespace", "", ""])
        writer.writerows(rows)

    bin_path = outdir / _BIN_NAME
    generate(
        SimpleNamespace(
            input=[str(csv_path)],
            output=_BIN_NAME,
            size=hex(size),
            version=_NVS_VERSION,
            outdir=str(outdir),
        )
    )
    return bin_path
