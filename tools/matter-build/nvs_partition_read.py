"""Read a factory NVS partition back into a dict for post-mint validation.

ESP-IDF's documented NVS reader is invoked through its CLI and emits the
minimal JSON shape `build._validate_factory_identity` consumes: integer fields
decode to Python ints and string fields to Python strings.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_NVS_TOOL = Path("/opt/esp/idf/components/nvs_flash/nvs_partition_tool/nvs_tool.py")


def read_factory_partition(path: Path, namespace: str) -> dict[str, int | str]:
    """Parse one namespace of a factory NVS partition into a {key: value} dict.

    Args:
        path: Path to the factory partition binary.
        namespace: The NVS namespace to extract (e.g. "chip-factory"); entries
            in other namespaces are ignored.

    Returns:
        A dict of the namespace's written keys to their decoded values.
    """
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(_NVS_TOOL),
            "--dump",
            "minimal",
            "--format",
            "json",
            str(path),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    entries = json.loads(result.stdout)
    return {entry["key"]: entry["data"] for entry in entries if entry["namespace"] == namespace}
